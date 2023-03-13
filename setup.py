from setuptools import setup

setup(
    name='vcc',
    packages=['vcc', 'vcc.ns'],
    description='Client software for VLBI Operations Center (VCC)',
    version='1.2.0',
    url='http://github.com/',
    author='Mario',
    author_email='mario.berube@nviinc.com',
    keywords=['vlbi', 'vcc'],
    install_requires=['requests', 'sshtunnel', 'pika', 'toml', 'psutil', 'pexpect',
                      'pycryptodome', 'pyjwt', 'urllib3', 'PyQt5', 'tabulate'],
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'vcc=vcc.__main__:main',
            'vcc-test=vcc.users:main',
            'vcc-message=vcc.tools:main',
            'vcc-ns=vcc.ns.__main__:main',
            'dashboard=vcc.dashboard:main',
            'downtime=vcc.downtime:main',
            'master=vcc.master:main',
            'inbox=vcc.inbox:main',
            'vcc-config=vcc.config:main'
        ]
    },
)
