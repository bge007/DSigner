"""
Windows Certificate Store access and CNG signing.

Enumerates certificates from the CurrentUser "MY" store and signs
digests with their private keys via NCrypt. Because the signing
operation happens inside Windows CNG, it works with non-exportable
keys, smartcards and USB tokens (the provider shows its own PIN
prompt when required).
"""
import ctypes
import hashlib
import logging
import warnings
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime

from cryptography import x509
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
ncrypt = ctypes.WinDLL("ncrypt", use_last_error=True)

CERT_KEY_PROV_INFO_PROP_ID = 2
CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG = 0x00020000
CERT_NCRYPT_KEY_SPEC = 0xFFFFFFFF
BCRYPT_PAD_PKCS1 = 0x00000002


class CERT_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("dwCertEncodingType", wintypes.DWORD),
        ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
        ("cbCertEncoded", wintypes.DWORD),
        ("pCertInfo", ctypes.c_void_p),
        ("hCertStore", ctypes.c_void_p),
    ]


PCCERT_CONTEXT = ctypes.POINTER(CERT_CONTEXT)

crypt32.CertOpenSystemStoreW.restype = ctypes.c_void_p
crypt32.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
crypt32.CertCloseStore.restype = wintypes.BOOL
crypt32.CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
crypt32.CertEnumCertificatesInStore.restype = PCCERT_CONTEXT
crypt32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, PCCERT_CONTEXT]
crypt32.CertDuplicateCertificateContext.restype = PCCERT_CONTEXT
crypt32.CertDuplicateCertificateContext.argtypes = [PCCERT_CONTEXT]
crypt32.CertFreeCertificateContext.restype = wintypes.BOOL
crypt32.CertFreeCertificateContext.argtypes = [PCCERT_CONTEXT]
crypt32.CertGetCertificateContextProperty.restype = wintypes.BOOL
crypt32.CertGetCertificateContextProperty.argtypes = [
    PCCERT_CONTEXT, wintypes.DWORD, ctypes.c_void_p,
    ctypes.POINTER(wintypes.DWORD)]
crypt32.CryptAcquireCertificatePrivateKey.restype = wintypes.BOOL
crypt32.CryptAcquireCertificatePrivateKey.argtypes = [
    PCCERT_CONTEXT, wintypes.DWORD, ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.BOOL)]

ncrypt.NCryptSignHash.restype = ctypes.c_long
ncrypt.NCryptSignHash.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_ubyte), wintypes.DWORD,
    ctypes.POINTER(ctypes.c_ubyte), wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
ncrypt.NCryptFreeObject.restype = ctypes.c_long
ncrypt.NCryptFreeObject.argtypes = [ctypes.c_void_p]


class BCRYPT_PKCS1_PADDING_INFO(ctypes.Structure):
    _fields_ = [("pszAlgId", ctypes.c_wchar_p)]


_CNG_HASH_ALG = {"sha1": "SHA1", "sha256": "SHA256",
                 "sha384": "SHA384", "sha512": "SHA512"}


@dataclass
class WinCertificate:
    """A signing-capable certificate from the Windows store."""
    der: bytes
    subject: str
    issuer: str
    not_before: datetime
    not_after: datetime
    thumbprint: str
    # duplicated PCCERT_CONTEXT; holds a reference to the store
    ctx: object = field(repr=False)

    def free(self):
        if self.ctx:
            crypt32.CertFreeCertificateContext(self.ctx)
            self.ctx = None


def _name_cn(name):
    cns = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return cns[0].value if cns else name.rfc4514_string()


def list_certificates(store_name="MY"):
    """Certificates in the CurrentUser store that have a private key."""
    store = crypt32.CertOpenSystemStoreW(None, store_name)
    if not store:
        raise OSError(f"Cannot open certificate store {store_name!r} "
                      f"(error {ctypes.get_last_error()})")

    certs = []
    try:
        ctx = None
        while True:
            ctx = crypt32.CertEnumCertificatesInStore(store, ctx)
            if not ctx:
                break

            # only certificates that are linked to a private key
            cb = wintypes.DWORD(0)
            if not crypt32.CertGetCertificateContextProperty(
                    ctx, CERT_KEY_PROV_INFO_PROP_ID, None, ctypes.byref(cb)):
                continue

            der = ctypes.string_at(ctx.contents.pbCertEncoded,
                                   ctx.contents.cbCertEncoded)
            try:
                with warnings.catch_warnings():
                    # some machine certs have nonstandard-length attributes
                    warnings.simplefilter("ignore")
                    parsed = x509.load_der_x509_certificate(der)
            except Exception:
                logger.exception("Skipping unparseable certificate")
                continue

            certs.append(WinCertificate(
                der=der,
                subject=_name_cn(parsed.subject),
                issuer=_name_cn(parsed.issuer),
                not_before=parsed.not_valid_before_utc,
                not_after=parsed.not_valid_after_utc,
                thumbprint=hashlib.sha1(der).hexdigest().upper(),
                ctx=crypt32.CertDuplicateCertificateContext(ctx),
            ))
    finally:
        crypt32.CertCloseStore(store, 0)

    certs.sort(key=lambda c: c.not_after, reverse=True)
    return certs


def sign_digest(win_cert, digest, digest_algorithm="sha256"):
    """Sign a pre-computed digest with the certificate's private key
    (RSA PKCS#1 v1.5) via Windows CNG."""
    alg = _CNG_HASH_ALG.get(digest_algorithm.lower())
    if alg is None:
        raise ValueError(f"Unsupported digest algorithm: {digest_algorithm}")

    hkey = ctypes.c_void_p()
    key_spec = wintypes.DWORD()
    must_free = wintypes.BOOL()

    ok = crypt32.CryptAcquireCertificatePrivateKey(
        win_cert.ctx, CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG, None,
        ctypes.byref(hkey), ctypes.byref(key_spec), ctypes.byref(must_free))
    if not ok:
        raise OSError(
            f"Cannot access the private key of '{win_cert.subject}' "
            f"(Windows error {ctypes.get_last_error()}). If the key is on "
            f"a token, make sure it is connected.")

    try:
        if key_spec.value != CERT_NCRYPT_KEY_SPEC:
            raise OSError(
                f"The private key of '{win_cert.subject}' uses a legacy "
                f"CryptoAPI provider that is not supported.")

        padding = BCRYPT_PKCS1_PADDING_INFO(alg)
        buf_in = (ctypes.c_ubyte * len(digest)).from_buffer_copy(digest)
        out_len = wintypes.DWORD(0)

        status = ncrypt.NCryptSignHash(
            hkey, ctypes.byref(padding), buf_in, len(digest),
            None, 0, ctypes.byref(out_len), BCRYPT_PAD_PKCS1)
        if status != 0:
            raise OSError(f"NCryptSignHash failed with status "
                          f"0x{status & 0xFFFFFFFF:08X}")

        sig_buf = (ctypes.c_ubyte * out_len.value)()
        status = ncrypt.NCryptSignHash(
            hkey, ctypes.byref(padding), buf_in, len(digest),
            sig_buf, out_len.value, ctypes.byref(out_len), BCRYPT_PAD_PKCS1)
        if status != 0:
            raise OSError(f"NCryptSignHash failed with status "
                          f"0x{status & 0xFFFFFFFF:08X}")

        return bytes(sig_buf[:out_len.value])
    finally:
        if must_free.value:
            ncrypt.NCryptFreeObject(hkey)
