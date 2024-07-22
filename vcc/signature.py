from time import time
import json
from datetime import datetime
from Crypto.Cipher import PKCS1_OAEP, AES
from base64 import b64decode

import jwt
import uuid
from cryptography.hazmat.primitives import serialization

from vcc import settings, VCCError, decrypt

private_key = None
secret_key = None


# Make signature and encode using ssh private key
def make(group_id, data=None, exp=0):
    global private_key, secret_key

    if private_key is None:
        with open(settings.RSAkey.path, 'rb') as f:
            private_key = serialization.load_ssh_private_key(f.read(), password=None)
        secret_key = str(uuid.uuid4())

    code, uid = getattr(settings.Signatures, group_id)
    required = {'code': code, 'group': group_id, 'secret': secret_key}
    data = dict(**data, **required) if data else required
    if exp > 0:
        data['exp'] = time() + exp
    # use user key to encode Jason Web Token
    # return {'token': jwt.encode(payload=data, key=f'#$&{uid[-12:]}{uid[:8]}&$#', algorithm='HS256',
    #                            headers={'uid': uid})}
    # Use user private key to encode Jason Web Token
    return {'token': jwt.encode(data, private_key, algorithm='RS256', headers={'uid': uid})}


# Validate signature of information received by VCC
def _validate(rsp):
    if not (token := rsp.headers.get('token')):
        return None
    headers = jwt.get_unverified_header(token)
    if not headers:
        raise VCCError('Invalid signature [no header in token]')
    uid = getattr(settings.Signatures, headers.get('group'), (None, None, None))[1]
    if not uid:
        raise VCCError('Invalid signature [invalid group]')
    try:
        info = jwt.decode(token, f'#$&{uid[-12:]}{uid[:8]}&$#', algorithms=headers['alg'])
        return json.loads(decrypt(info['encrypted'], uid[9:23]).decode()) if 'encrypted' in info else info
    except (jwt.exceptions.ExpiredSignatureError, jwt.exceptions.InvalidSignatureError) as exc:
        raise VCCError(f'signature {str(exc)}')


def validate(rsp):
    if not (token := rsp.headers.get('token')):
        return None
    headers = jwt.get_unverified_header(token)
    print('headers', headers)
    if not headers:
        raise VCCError('Invalid signature [no header in token]')
    try:
        info = jwt.decode(token, secret_key, algorithms=headers['alg'])
        print('info', info)
        # return json.loads(decrypt(info['encrypted'], uid[9:23]).decode()) if 'encrypted' in info else info
        return json.loads(decrypt(info['encrypted'], secret_key).decode()) if 'encrypted' in info else info
    except (jwt.exceptions.ExpiredSignatureError, jwt.exceptions.InvalidSignatureError) as exc:
        raise VCCError(f'signature {str(exc)}')
