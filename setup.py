from setuptools import setup

setup(
    name='vcc',
    packages=['vcc', 'vcc.ns', 'vcc.images'],
    description='Client software for VLBI Operations Center (VCC)',
    version='1.3.1',
    url='http://github.com/',
    author='Mario',
    author_email='mario.berube@nviinc.com',
    keywords=['vlbi', 'vcc'],
    install_requires=['requests', 'sshtunnel', 'pika', 'toml', 'psutil', 'pexpect', 'setuptools',
                      'pycryptodome', 'pyjwt', 'urllib3', 'tabulate', 'tkcalendar'],
    include_package_data=True,
    package_data={'': ['images/info.png', 'images/warning.png', 'images/urgent.png']},
    entry_points={
        'console_scripts': [
            'vcc=vcc.__main__:main',
            'vcc-test=vcc.users:main',
            'vcc-message=vcc.tools:main',
            'vcc-ns=vcc.ns.__main__:main',
            'ses-info=vcc.ns.sesinfo:main',
            'dashboard=vcc.dashboard:main',
            'downtime=vcc.downtime:main',
            'master=vcc.master:main',
            'inbox=vcc.inbox:main',
            'urgent=vcc.urgent:main',
            'vcc-config=vcc.config:main',
            'testing=vcc.windows:main'
        ]
    },
)
