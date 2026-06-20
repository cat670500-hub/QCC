import datetime
import os
import sys
import socket
import ipaddress
import subprocess

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

def main():
    print("正在檢查並安裝 SSL 憑證產生所需套件 (cryptography)...")
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        print("[資訊] 未安裝 cryptography，正在為您自動安裝...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography", "pyOpenSSL"])
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

    print("正在產生 self-signed 憑證與私密金鑰...")
    # 產生私密金鑰
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # 憑證主體與簽發者資訊
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "TW"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Taipei"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Taipei"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Portable"),
        x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1"),
    ])
    
    # 建立 Subject Alternative Names (SAN)
    local_ip = get_local_ip()
    print(f"偵測到本機 LAN IP: {local_ip}")
    
    alt_names = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    if local_ip != "127.0.0.1":
        try:
            alt_names.append(x509.IPAddress(ipaddress.IPv4Address(local_ip)))
        except Exception as e:
            print(f"[警告] 無法將本機 IP {local_ip} 加入 SAN 欄位: {e}")
            
    # 建立憑證 (有效期限 10 年)
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow() - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=3650)
    ).add_extension(
        x509.SubjectAlternativeName(alt_names),
        critical=False,
    ).sign(key, hashes.SHA256())
    
    # 寫入私鑰
    with open("key.pem", "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    
    # 寫入憑證
    with open("cert.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
        
    print("\n==================================================")
    print("  [成功] cert.pem 與 key.pem 已順利產生！")
    print("  主系統已啟動安全模式 (HTTPS) 支援。")
    print("==================================================")

    # 匯入 Windows 受信任儲存區
    print("\n正在向 Windows 系統匯入並信任此憑證...")
    try:
        subprocess.check_call(["certutil", "-addstore", "-user", "-f", "Root", "cert.pem"])
        print("[系統] 已成功將憑證安裝至目前使用者的「受信任的根憑證授權單位」！")
    except Exception as e:
        print(f"[警告] 無法自動安裝憑證至 Windows 憑證存放區: {e}")
        print("請手動點兩下 cert.pem 並將其安裝至「受信任的根憑證授權單位」。")

if __name__ == "__main__":
    main()
