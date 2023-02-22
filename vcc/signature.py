from time import time
import json
from Crypto.Cipher import PKCS1_OAEP, AES
from base64 import b64decode

import jwt

from vcc import settings, VCCError, decrypt


# Make signature and encode using ssh private key
def make(group_id, data=None, exp=0):
    code, uid = getattr(settings.Signatures, group_id)
    required = {'code': code, 'group': group_id}
    data = dict(**data, **required) if data else required
    if exp > 0:
        data['exp'] = time() + exp
    # use user key to encode Jason Web Token
    return {'token': jwt.encode(payload=data, key=f'#$&{uid[-12:]}{uid[:8]}&$#', algorithm='HS256',
                                headers={'uid': uid})}


# Validate signature of information received by VCC
def validate(rsp):
    token = rsp.headers.get('token')
    if not token:
        raise VCCError('Invalid signature [no token]')
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
