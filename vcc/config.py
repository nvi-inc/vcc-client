import os
import platform
from pathlib import Path
import sys
import traceback
if platform.system() != "Windows":
    import pwd
    import getpass

import toml
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP, AES
from base64 import b64decode


# Decode the encrypted file and create config file and extra scripts
class ConfigDecoder:

    def __init__(self):

        self.user = None if platform.system() == "Windows" else pwd.getpwnam(getpass.getuser())
        self.wd, self.exec = Path(os.getcwd()), Path(sys.executable).parent
        self.config, self.config_option = None, False
        self.bin = Path(self.wd, 'bin')
        self.bin.mkdir(exist_ok=True)
        self.messages = Path(self.wd, 'messages')
        self.messages.mkdir(exist_ok=True)

    def chown(self, path: Path, mode: int, user=None) -> None:
        if platform.system() != "Windows":
            (uid, gid) = (user.pw_uid, user.pw_gid) if user else (os.getuid(), os.getgid())
            os.chown(path, uid, gid)
        path.chmod(mode)

    def decode(self, infile, outfile, keyfile):
        try:
            private_key = RSA.import_key(open(keyfile, "rb").read())
            if not (path := Path(infile)).exists() or path.stat().st_size == 0:
                print(f"{outfile} does not exist or is empty!")
                exit(0)

            with open(infile, 'r') as f_in:
                enc_key, nonce, tag, encrypted = [b64decode(bytes.fromhex(x)) for x in f_in.read().split('-')]
                key = PKCS1_OAEP.new(private_key).decrypt(enc_key)
                decoded = AES.new(key, AES.MODE_EAX, nonce).decrypt_and_verify(encrypted, tag).decode('utf-8')
                # Load decoded data into memory
                settings = toml.loads(decoded)

                # Test output file
                if not outfile:
                    outfile = '/usr2/control/vcc.ctl' if settings['Signatures'].get('NS') else 'vcc.ctl'
                self.config = Path(outfile)
                if self.config.exists():
                    while True:
                        if (answer := input(f'{self.config} already exists! Overwrite it? (y/n)').lower()) == 'y':
                            self.chown(self.config, 0o666)
                            break
                        if answer == 'n':
                            print('New configuration not saved!')
                            return

                # Save configuration
                with open(self.config, 'w') as f_out:
                    f_out.write(decoded)
                    p = str(Path(keyfile).expanduser().absolute())
                    if platform.system() == "Windows":
                        p = p.replace('\\', '\\\\')
                    f_out.write(f'\n# Private ssh key to access VCC\n[RSAkey]\npath = \"{p}\"\n')
                print(f'VCC configuration saved in {self.config}')

                # Create some scripts in bin folder that could be added to path
                if settings['Signatures'].get('NS'):
                    prog, oper = pwd.getpwnam('prog'), pwd.getpwnam('oper')
                    self.chown(self.config, 0o664, user=oper)
                    self.chown(self.bin, 0o775, user=prog)
                    self.chown(self.messages, 0o775, user=oper)
                    log_dir = Path('/usr2/log/vcc')
                    log_dir.mkdir(exist_ok=True)
                    self.chown(log_dir, 0o775, user=oper)
                    self.make_service_file(log_dir)  # service file for systemd
                    self.make_script('vccmon', nohup=True)
                    self.make_script('vccns')
                    self.make_script('fslog')
                    self.make_script('vcc', action='inbox NS', nohup=True)
                else:
                    self.config_option = True
                    self.make_script('vcc', action='master')
                    self.make_script('vcc', action='inbox', nohup=True)

                self.make_script('vcc')
                self.make_script('vcc', action='dashboard', nohup=True)
                self.make_script('vcc', action='sumops', nohup=True, cmdline=['-r', '--report'])
                self.make_script('vcc', action='downtime', nohup=True, cmdline=['-r', '--report'])
                self.make_script('vcc', action='urgent', nohup=True)
        except FileNotFoundError:
            print(f'Could not create {self.config}')
            print(traceback.format_exc())
        except TypeError as exc:
            print(str(exc))
            print(traceback.format_exc())
            return None

    # Make a script that could be used as a command
    def make_script(self, app, action='', nohup=False, cmdline=None):

        path = Path(self.bin, action.split()[0] if action else app)
        pre, post = ('nohup ', ' >/dev/null 2>&1 &') if nohup else ('', '')
        config_option = f" -c {self.config.absolute()}" if self.config_option else ""
        cmd = f"{str(Path(self.exec, app))}{config_option} {action} $@"
        with open(path, 'w') as f:
            print('#!/bin/bash', file=f)
            if cmdline:
                print('for i in "$@" ; do', file=f)
                tests = [f'[[ $i == "{opt}" ]]' for opt in cmdline]
                print(f'    if {" || ".join(tests)} ; then', file=f)
                print(f"        {cmd}", file=f)
                print('        exit 1', file=f)
                print('    fi', file=f)
                print('done\n', file=f)
            print(f"{pre}{cmd}{post}\n", file=f)

        self.chown(path, 0o775, self.user)

    def make_service_file(self, log_dir):
        filename = Path(log_dir, 'service.log')
        with open(Path(os.getcwd(), 'vccmon.service'), 'w') as f:
            print('[Unit]', file=f)
            print('Description=VCC Network Station service', file=f)
            print('After=network-online.target', file=f)
            print('Wants=network-online.target', file=f)
            print(file=f)
            print('[Service]', file=f)
            print(f'ExecStart={str(Path(self.exec, "vccmon"))}', file=f)
            print(f'StandardOutput=append:{filename}', file=f)
            print(f'StandardError=append:{filename}', file=f)
            print('Restart=always', file=f)
            print('User=oper', file=f)
            print('Group=rtx', file=f)
            print(file=f)
            print('[Install]', file=f)
            print('WantedBy=multi-user.target', file=f)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Create VCC config file')
    parser.add_argument('-o', '--output', help='output configuration file', required=False)
    parser.add_argument('input', help='path to encrypted file or vcc.ctl')
    parser.add_argument('key', help='private rsa key file', default='~/.ssh/id_rsa', nargs='?')

    args = parser.parse_args()

    in_file, key_file = [Path(os.path.expanduser(x)) for x in [args.input, args.key]]
    if not in_file.exists():
        print(f'Input file {args.input} doest not exist')
    elif not key_file.exists():
        print(f'RSA key file {args.key} doest not exist')
    else:
        ConfigDecoder().decode(in_file, args.output, key_file)


if __name__ == '__main__':

    sys.exit(main())
