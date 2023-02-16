import os
from pathlib import Path

import toml
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP, AES


def decode_config(input_file, output_file, key_file):
    try:
        private_key = RSA.import_key(open(key_file, "rb").read())

        with open(input_file, 'rb') as f_in:
            enc_key, nonce, tag, encrypted = [f_in.read(x) for x in (private_key.size_in_bytes(), 16, 16, -1)]
            key = PKCS1_OAEP.new(private_key).decrypt(enc_key)
            config = AES.new(key, AES.MODE_EAX, nonce).decrypt_and_verify(encrypted, tag).decode('utf-8')
            settings = toml.loads(config)
            output_file = Path(output_file) if output_file else \
                Path('/usr2/control/vcc.ctl' if settings['Signatures'].get('NS') else 'vcc.ctl')
            if output_file.exists():
                while True:
                    answer = input(f'{output_file} already exists! Overwrite it? (y/n)').lower()
                    if answer == 'y':
                        break
                    if answer == 'n':
                        print('Configuration not saved!')
                        return

            with open(output_file, 'w') as f_out:
                f_out.write(config)
                f_out.write(f'\n# Private key to access VCC\n[RSAkey]\n'
                            f'path = \"{os.path.abspath(os.path.expanduser(key_file))}\"\n')
            print(f'VCC configuration saved in {output_file}')
    except FileNotFoundError:
        print(f'Could not create {output_file}')
    except TypeError as exc:
        print(str(exc))
        return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Create VCC config file')
    parser.add_argument('-o', '--output', help='output configuration file', required=False)
    parser.add_argument('input', help='input binary file')
    parser.add_argument('key', help='private rsa key file', default='~/.ssh/id_rsa', nargs='?')

    args = parser.parse_args()

    in_file, key_file = [Path(os.path.expanduser(x)) for x in [args.input, args.key]]
    if not in_file.exists():
        print(f'Input file {args.input} doest not exist')
    elif not key_file.exists():
        print(f'RSA key file {args.input} doest not exist')
    else:
        decode_config(in_file, args.output, key_file)


if __name__ == '__main__':

    import sys
    sys.exit(main())
