from setuptools import setup

setup(
    name='vcc',
    packages=['vcc', 'vcc.ns'],
    description='VCC Schedule uploader for Operations Center client',
    version='1.1.0',
    url='http://github.com/example/linode_example',
    author='Mario',
    author_email='mario.berube@nviinc.com',
    keywords=['vlbi', 'vcc'],
    install_requires=['requests', 'sshtunnel', 'pika', 'toml', 'psutil', 'pexpect',
                      'pycryptodome', 'pyjwt', 'urllib3', 'PyQt5', 'tabulate'],
    include_package_data=True,
    # package_data={'': ['data/sv.bin']},
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
