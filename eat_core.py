"""Shared EatDetails logic used by CLI and the local web app."""
import requests
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToDict
import MajorLoginRes_pb2 as pb2

# Suppress insecure-request warnings for the game login endpoint (verify=False).
requests.packages.urllib3.disable_warnings(  # type: ignore[attr-defined]
    requests.packages.urllib3.exceptions.InsecureRequestWarning  # type: ignore[attr-defined]
)


class SimpleProtobuf:
    @staticmethod
    def encode_varint(value):
        result = bytearray()
        while value > 127:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value)
        return result

    @staticmethod
    def encode_string(field, value):
        result = bytearray()
        result.extend(SimpleProtobuf.encode_varint((field << 3) | 2))
        result.extend(SimpleProtobuf.encode_varint(len(value)))
        result.extend(value.encode() if isinstance(value, str) else value)
        return result

    @staticmethod
    def encode_int32(field, value):
        result = bytearray()
        result.extend(SimpleProtobuf.encode_varint((field << 3) | 0))
        result.extend(SimpleProtobuf.encode_varint(value))
        return result


def encrypt_api(plain_text):
    if isinstance(plain_text, str):
        plain_text = bytes.fromhex(plain_text)
    key = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
    iv = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(pad(plain_text, AES.block_size)).hex()


def create_login_payload(open_id, access_token, platform):
    payload = bytearray()
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fields = {
        3: t, 4: 'free fire', 5: 1, 7: '2.127.16', 8: 'Android OS 9 / API-28 (PQ3A.190605.06171433/3793265)',
        9: 'Handheld', 10: 'Vodafone IN', 11: 'WIFI', 12: 1334, 13: 750, 14: '240',
        15: 'x86-64 SSE3 SSE4.1 SSE4.2 AVX | 2865 | 6', 16: 5955, 17: 'Adreno (TM) 750',
        18: 'OpenGL ES 3.1 v1', 19: 'Google|13b00015-be2c-4599-a9c3-f364dbc5b348',
        20: '49.47.131.178', 21: 'en', 22: open_id, 23: str(platform), 24: 'Handheld',
        25: 'samsung SM-N960N', 26: 'IND', 29: access_token, 30: 1, 41: 'Vodafone IN',
        42: 'WIFI', 57: '1ac4b80ecf0478a44203bf8fac6120f5', 60: 59938, 61: 52289, 62: 2519,
        63: 732, 64: 28954, 65: 32203, 66: 54892, 67: 59938, 73: 1,
        74: '/data/app/com.dts.freefiremax-UCo8_GShaEs0xRyfprqGAQ==/lib/arm64', 76: 2,
        77: '8eba3fdaf92790f192e94d156d531212|/data/app/com.dts.freefiremax-UCo8_GShaEs0xRyfprqGAQ==/base.apk',
        78: 2, 79: 2, 81: '64', 83: '2019118047', 86: 'OpenGLES3', 87: 4095, 88: 4, 92: 28208,
        93: 'android_max', 94: 'KqsHT7z+pL+pQ77lIvmxgGBlZqNVSdFLu3HQp7kzLDtkHNMNhKU9jp3+5xtJu7gZeRZkqxpy0gEyxjQE9csYJaV5ZgE=',
        95: 111207, 96: '{"cur_rate":null,"support_etc2":true}', 97: 1, 98: 1,
        99: str(platform), 100: str(platform)
    }
    for field, value in fields.items():
        if isinstance(value, int):
            payload.extend(SimpleProtobuf.encode_int32(field, value))
        else:
            payload.extend(SimpleProtobuf.encode_string(field, value))
    payload.extend(SimpleProtobuf.encode_string(102, ''))
    return bytes(payload)


def normalize_eat_token(raw: str) -> str:
    """Accept raw token or reward URL; return only the access_token value."""
    value = (raw or "").strip().strip('"').strip("'")
    if not value:
        return ""

    # Full reward / any URL with access_token=...
    lower = value.lower()
    marker = "access_token="
    if marker in lower:
        # Find marker case-insensitively, then take value after it
        idx = lower.find(marker)
        value = value[idx + len(marker) :]
        # Cut off extra query/hash fragments
        for sep in ("&", "#", "?", " ", "\n", "\r", "\t"):
            if sep in value:
                value = value.split(sep, 1)[0]
        return value.strip()

    return value


def get_eat_details(access_token: str) -> dict:
    """Same flow as the terminal script. Returns the final details dict."""
    access_token = normalize_eat_token(access_token)
    if not access_token:
        raise ValueError("Access token is required.")

    res1 = requests.get(
        f"https://api-otrss.garena.com/support/callback/?access_token={access_token}",
        allow_redirects=True,
        timeout=30,
        verify=False,
    )
    if "access_token=" not in res1.url:
        raise RuntimeError("Could not resolve access token from Garena callback URL.")
    token2 = res1.url.split("access_token=")[1].split("&")[0]

    res2 = requests.get(
        f"https://ffmconnect.live.gop.garenanow.com/oauth/token/inspect?token={token2}",
        timeout=30,
        verify=False,
    )
    res2.raise_for_status()
    inspect_data = res2.json()

    open_id = inspect_data["open_id"]
    platform = inspect_data["platform"]

    payload = create_login_payload(open_id, token2, platform)
    encrypted = encrypt_api(payload.hex())
    headers = {
        "X-Unity-Version": "2018.4.11f1",
        "ReleaseVersion": "OB54",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-GA": "v1 1",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 7.1.2; ASUS_Z01QD Build/QKQ1.190825.002)",
        "Host": "loginbp.common.ggbluefox.com",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
    }
    res3 = requests.post(
        "https://loginbp.ggblueshark.com/MajorLogin",
        headers=headers,
        data=bytes.fromhex(encrypted),
        verify=False,
        timeout=30,
    )
    res3.raise_for_status()

    msg = pb2.MajorLoginRes()
    msg.ParseFromString(res3.content)
    login_data = MessageToDict(msg, preserving_proto_field_name=True)

    return {
        "access_token": str(token2),
        "account_id": str(login_data.get("account_id", "")),
    }
