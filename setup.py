from setuptools import setup

setup(
    name='vcc',
    packages=['vcc', 'vcc.ns', 'vcc.images'],
    description='Client software for VLBI Operations Center (VCC)',
    version='1.5.3',
    url='https://github.com/nvi-inc/vcc-client',
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
            'vccns=vcc.ns.__main__:main',
            'message-box=vcc.windows:main',
            'fslog=vcc.fslog:main',
            'sessions-wnd=vcc.tools:main',
            'dashboard=vcc.__main__:main',
            'sumops=vcc.__main__:main',
            'downtime=vcc.__main__:main',
            'master=vcc.__main__:main',
            'urgent=vcc.__main__:main',
            'inbox=vcc.__main__:main',
            'vcc-config=vcc.config:main',
            'inbox-ns=vcc.inbox:main',
            'vccmon=vcc.ns.service:main'
        ]
    },
)
