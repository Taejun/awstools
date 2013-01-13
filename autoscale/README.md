# AutoScaleCTL

AutoScaleCTL is a tool to manage your AWS AutoScaling configurations from a config file.

For more information, see http://eng.wish.com/advice-and-tools-for-aws-autoscaling/

## Installation

1.  Download code from GitHub
2.  `pip install -r pip-requirements` (you can probably skip this if you have a fairly recent `boto` installed)
3.  Run `sudo python setup.py install` (makes `autoscalectl` in `/usr/local/bin`, so you’ll probably need sudo here)

If you haven't already, setup your `boto` config file at `~/.boto` with:

    [Credentials] 
    aws_access_key_id = <your access key> 
    aws_secret_access_key = <your secret key>
    

## Usage

The first step is to copy and edit the sample `autoscale.yaml` to fit your configuration. A lot of sections are optional so you can start simple to play around and then build out more complexity as you go. It doesn't support every feature of AutoScale, but it supports a pretty good set. If you want to add more, feel free to send a pull request.

When that's done, run `autoscalectl [/path/to/autoscale.yaml]`.

One important note is that it doesn't support removing AutoScaling groups or alarms. So, if you delete a section from the config file, it won't be deleted in AWS. You've gotta take care of that one manually.
