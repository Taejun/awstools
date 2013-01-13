from setuptools import setup, Extension

setup(name='autoscalectl',
    version='0.1',
    author='Adam Flynn',
    author_email='adam@contextlogic.com',
    description="Tool to manage AWS AutoScale via a config file",
    keywords="aws, infrastructure, autoscale",
    license="MIT",
    url="http://www.github.com/ContextLogic/awstools",

    entry_points={
        'console_scripts': [
            'autoscalectl = autoscalectl:main'
        ]
    },
    scripts=['autoscalectl.py']
)
