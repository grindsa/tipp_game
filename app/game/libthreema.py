#!/usr/bin/python
# -*- coding: utf-8 -*-
""" threema library to send messages """
from __future__ import print_function
from __future__ import absolute_import
import random
import binascii
import sys
import libnacl
from urllib.request import urlopen
from urllib.parse import urlencode

try:
    import libnacl
    import libnacl.public
    import libnacl.encode
except BaseException:
    # print('error')
    pass

def convert_byte_to_string(value):
    """ convert a variable to string if needed """
    if hasattr(value, 'decode'):
        return value.decode()
    else:
        return value

def convert_string_to_byte(value):
    """ convert a variable to byte if needed """
    if hasattr(value, 'encode'):
        return value.encode()
    else:
        return value

def tr_get_credits(_id, secret):
    """ tr_get_credits """
    url = 'https://msgapi.threema.ch/credits?from={0}&secret={1}'.format(_id, secret)
    fso = urlopen(url)
    try:
        num = int(fso.read())
    except BaseException:
        num = None

    return num

def tr_lookup_pubkey(receiver, sender, threema_secret):
    """ lookup public key """
    url = 'https://msgapi.threema.ch/pubkeys/'+receiver
    params = urlencode({'from': sender, 'secret': threema_secret})
    # params = params.encode('ascii')
    url = url +'?'+ params
    fso = urlopen(url)
    pkey = fso.read()
    if pkey:
        return 'public:{0}'.format(convert_byte_to_string(pkey))
    else:
        return None

def decode_key(encoded_key):
    """ decode key """
    # Split key
    try:
        (_type, _key) = encoded_key.split(':')
    except BaseException:
        print('Invalid key format')
        _type = None
        _key = None
        sys.exit(0)

    # De-hexlify
    key = libnacl.encode.hex_decode(_key)
    # Convert to SecretKey or PublicKey
    if _type.lower() == 'private':
        key = libnacl.public.SecretKey(key)
    elif _type.lower() == 'public':
        key = libnacl.public.PublicKey(key)

    return key

def encrypt(private, public, data):
    """
    Encrypt a message.

    Arguments:
        - `private`: Private key of the sender.
        - `public`: The public key of the recipient.
        - `data`: Message data (bytes).

    Return a tuple of the nonce and the encrypted message. Both
    values are hex-encoded.
    """
    # Generate 0 < padding < 256
    padding_length = random.randint(1, 255)
    padding = bytes([padding_length] * padding_length)

    # Assemble and encrypt the payload
    box = libnacl.public.Box(sk=private, pk=public)

    data_pad = data + padding
    (nonce, message) = box.encrypt(data_pad, pack_nonce=False)

    # Return as hex
    return (binascii.hexlify(nonce).decode('ascii'), binascii.hexlify(message).decode('ascii'))

def from_bytes(data, big_endian=False):
    """ from bytes """
    if isinstance(data, str):
        data = bytearray(data)
    if big_endian:
        data = reversed(data)
    num = 0
    for offset, byte in enumerate(data):
        num += byte << (offset * 8)

    return num

def decrypt(private, public, nonce, message):
    """
    Decrypt a message.

    Arguments:
        - `private`: Private key of the sender.
        - `public`: The public key of the recipient.
        - `nonce`: The nonce of the encrypted message.
        - `data`: Encrypted message (bytes).

    Return an instance of either a :class:`DeliveryReceipt` or a
    :class:`TextMessage`.
    """
    # Un-hexlify
    nonce, message = binascii.unhexlify(nonce), binascii.unhexlify(message)

    # Decrypt payload
    box = libnacl.public.Box(sk=private, pk=public)
    payload = box.decrypt(message, nonce)

    # Remove padding and type
    type_ = payload[:1]
    # print(type_)
    # padding_length = int.from_bytes(payload[-1:], byteorder='little')
    padding_length = from_bytes(payload[-1:])
    payload = payload[1:-padding_length]

    return(type_, payload)

def send_e2e(sender, receiver, message, nonce, secret):
    """ send message """
    url = 'https://msgapi.threema.ch/send_e2e'

    # prepare message
    params = urlencode({'box': message, 'from': sender, 'to': receiver, 'secret': secret, 'nonce': nonce})
    params = params.encode('ascii')

    # send message
    try:
        fso = urlopen(url, params, timeout=2)
        result = fso.read()
    except urllib.error.URLError as err:
        print("There was an error: %r" % err)
        result = None
    return result
