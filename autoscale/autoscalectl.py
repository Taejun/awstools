import sys
import yaml
import os.path
import boto.ec2.autoscale
import boto.ec2.cloudwatch
from boto.ec2.autoscale import LaunchConfiguration, AutoScalingGroup, Tag, \
        ScalingPolicy
from boto.ec2.cloudwatch import MetricAlarm
from collections import defaultdict

class AutoScaleCtl(object):
    AUTOSCALE_CONFIG = "autoscale.yaml"

    DEFAULT_REGION = 'us-west-1'

    AS_NOTIFICATIONS = ['autoscaling:%s' % n for n in
                                ['EC2_INSTANCE_LAUNCH',
                                 'EC2_INSTANCE_LAUNCH_ERROR',
                                 'EC2_INSTANCE_TERMINATE',
                                 'EC2_INSTANCE_TERMINATE_ERROR']]

    def __init__(self, config=None):
        if not config:
            config = self.AUTOSCALE_CONFIG

        config = os.path.abspath(config)

        if not os.path.isfile(config):
            raise IOError("Cannot find config file at %s" % config)

        print "Loading config at %s" % config

        with open(config) as f:
            self.as_config = yaml.load(f)

        self.region = self.as_config.get('region', self.DEFAULT_REGION)
        self.as_conn = boto.ec2.autoscale.connect_to_region(self.region)
        self.cw_conn = boto.ec2.cloudwatch.connect_to_region(self.region)

        self.policies = self.as_config.get('policies', {})

        # if user_data is a list, join it with \n... multiline strings don't
        # work well here because we need YAML in the user data for Ubuntu
        # cloud-config and getting indentation right in YAML multiline strings
        # is a pain
        if 'user_data' not in self.as_config:
            self.user_data = ''
        elif isinstance(self.as_config['user_data'], list):
            self.user_data = "\n".join(self.as_config['user_data'])
        else:
            self.user_data = self.as_config['user_data']

    def run(self):
        all_lcs = self.as_conn.get_all_launch_configurations()
        lc_by_group = defaultdict(list)
        lc_max_num_by_group = defaultdict(int)

        for lc in all_lcs:
            name, num = lc.name.split('-')
            num = int(num)

            lc_by_group[name].append(lc)

            if num > lc_max_num_by_group[name]:
                lc_max_num_by_group[name] = num

        all_ags = self.as_conn.get_all_groups()
        ag_by_name = {}
        for ag in all_ags:
            ag_by_name[ag.name] = ag

        for group_name, config in self.as_config["groups"].iteritems():
            print "Configuring %s" % group_name
            use_lc = None
            lc_to_delete = []
            for lc in lc_by_group[group_name]:
                if use_lc is None and \
                   lc.image_id == config['ami'] and \
                   lc.key_name == config['ssh_key'] and \
                   lc.instance_type == config['instance_type'] and \
                   lc.security_groups == [config['security_group']] and \
                   lc.user_data == self.user_data:
                    print " Found LaunchConfig %s that matches profile" % \
                            lc.name
                    use_lc = lc
                else:
                    lc_to_delete.append(lc)

            print " Found %d LaunchConfigurations to delete" % len(lc_to_delete)

            if not use_lc:
                print " Making LaunchConfiguration for %s" % group_name
                lc_num = lc_max_num_by_group[group_name] + 1
                use_lc = LaunchConfiguration(
                                 name="%s-%d" % (group_name, lc_num),
                                 image_id=config['ami'],
                                 key_name=config['ssh_key'],
                                 instance_type=config['instance_type'],
                                 security_groups=[config['security_group']],
                                 user_data=self.user_data)
                self.as_conn.create_launch_configuration(use_lc)

            if group_name in ag_by_name:
                print " Found existing AutoScalingGroup, updating"
                ag = ag_by_name[group_name]
                ag_exists = True
            else:
                print " Making new AutoScalingGroup"
                ag = AutoScalingGroup()
                ag_exists = False

            # config ASG as we want it
            ag.name = group_name
            ag.launch_config_name = use_lc.name
            ag.availability_zones = config['zones']
            ag.desired_capacity = config['capacity']
            ag.min_size = config['min_size']
            ag.max_size = config['max_size']

            # create or update as appropriate
            if ag_exists:
                ag.update()
            else:
                self.as_conn.create_auto_scaling_group(ag)

            # make it send e-mail whenever it does something
            if 'notification_topic' in self.as_config:
                # NOTE [adam Sept/18/12]: this is a hack designed to work
                #      around that boto support for this isn't in a release yet.
                #      when the next release is out, we should uncomment the
                #      code below.
                params = {'AutoScalingGroupName': ag.name,
                          'TopicARN': self.as_config['notification_topic'] }
                self.as_conn.build_list_params(params, self.AS_NOTIFICATIONS,
                                               'NotificationTypes')
                self.as_conn.get_status('PutNotificationConfiguration', params)
                #as_conn.put_notification_configuration(
                #       ag.name,
                #       self.as_config['notification_topic'],
                #       self.AS_NOTIFICATIONS)

            tags = []
            for tag_name, tag_value in config.get('tags', {}).iteritems():
                print " Adding tag %s = %s" % (tag_name, tag_value)
                tags.append(Tag(key=tag_name, value=tag_value,
                                propagate_at_launch=True,
                                resource_id=ag.name))

            self.as_conn.create_or_update_tags(tags)

            for lc in lc_to_delete:
                print " Deleting old LaunchConfiguration %s" % lc.name
                lc.delete()

            for alarm_name, alarm_cfg in config.get('alarms', {}).iteritems():
                alarm_policy_arn = self.make_policy(group_name,
                                          alarm_cfg['policy'])

                alarm_name = '%s|%s|%s' % (group_name,
                                           alarm_cfg['policy'],
                                           alarm_cfg['metric'])
                alarm = MetricAlarm(
                    name=alarm_name,
                    namespace=alarm_cfg['namespace'],
                    metric=alarm_cfg['metric'],
                    statistic='Average',
                    dimensions={'AutoScalingGroupName': group_name},
                    comparison=alarm_cfg['comparison'],
                    threshold=alarm_cfg['threshold'],
                    period=alarm_cfg['period'],
                    evaluation_periods=alarm_cfg.get('evaluation_periods', 1),
                    alarm_actions=[alarm_policy_arn])

                self.cw_conn.put_metric_alarm(alarm)

    def make_policy(self, group_name, policy_name):
        """
            Makes a given AutoScaling policy for the given group

            Returns the policy's ARN
        """
        if policy_name not in self.policies:
            print " Cannot find AutoScale policy %s" % policy_name
            return None

        policy = self.policies[policy_name]

        as_policy = ScalingPolicy(name='%s|%s' % (group_name, policy_name),
                               adjustment_type=policy['type'],
                               as_name=group_name,
                               scaling_adjustment=policy['adjustment'],
                               cooldown=policy.get('cooldown', None))

        resp = self.as_conn.create_scaling_policy(as_policy)
        return resp.PolicyARN

def main():
    config = sys.argv[1] if len(sys.argv) >= 2 else None

    ctl = AutoScaleCtl(config)
    ctl.run()

if __name__ == "__main__":
    main()
