#!/usr/bin/env python3
"""Make a ZIP of fake KDMs for the encrypted sample DCPs (see
dev/make_sample_dcps.py), to try the KDM check of the UI: for each DCP, a
KDM valid now for two screens, an expired one, one not valid yet, one that
misses a key and one for another version of the film. Plus a file that is
not a KDM. Their keys are random: only their public part is checked.

    python3 dev/make_sample_kdms.py sample-dcps sample-kdms.zip
"""
import os
import sys
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))

from dcpcheck import scanner  # noqa: E402

KDM = """<?xml version="1.0" encoding="UTF-8"?>
<DCinemaSecurityMessage xmlns="http://www.smpte-ra.org/schemas/430-3/2006/ETM" xmlns:dsig="http://www.w3.org/2000/09/xmldsig#" xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <AuthenticatedPublic Id="ID_AuthenticatedPublic">
    <MessageId>urn:uuid:{message_id}</MessageId>
    <MessageType>http://www.smpte-ra.org/430-1/2006/KDM#kdm-key-type</MessageType>
    <AnnotationText>{title} :: {screen}</AnnotationText>
    <IssueDate>{issued}</IssueDate>
    <Signer><dsig:X509IssuerName>dnQualifier=x,CN=.dcpomatic.smpte-430-2.INTERMEDIATE,OU=dcpomatic.com,O=dcpomatic.com</dsig:X509IssuerName><dsig:X509SerialNumber>6</dsig:X509SerialNumber></Signer>
    <RequiredExtensions>
      <KDMRequiredExtensions xmlns="http://www.smpte-ra.org/schemas/430-1/2006/KDM">
        <Recipient>
          <X509IssuerSerial><dsig:X509IssuerName>dnQualifier=y,CN=.ca.example.com,O=example.com</dsig:X509IssuerName><dsig:X509SerialNumber>42</dsig:X509SerialNumber></X509IssuerSerial>
          <X509SubjectName>dnQualifier=z,CN=SM.{screen_id}.IMB.example.com,OU=example.com,O=example.com</X509SubjectName>
        </Recipient>
        <CompositionPlaylistId>urn:uuid:{cpl_id}</CompositionPlaylistId>
        <ContentAuthenticator>AAAAAAAAAAAAAAAAAAAAAAAAAAA=</ContentAuthenticator>
        <ContentTitleText>{title}</ContentTitleText>
        <ContentKeysNotValidBefore>{not_before}</ContentKeysNotValidBefore>
        <ContentKeysNotValidAfter>{not_after}</ContentKeysNotValidAfter>
        <AuthorizedDeviceInfo>
          <DeviceListIdentifier>urn:uuid:{device_id}</DeviceListIdentifier>
          <DeviceListDescription>{screen}</DeviceListDescription>
          <DeviceList><CertificateThumbprint>2jmj7l5rSw0yVb/vlWAYkK/YBwk=</CertificateThumbprint></DeviceList>
        </AuthorizedDeviceInfo>
        <KeyIdList>
{keys}        </KeyIdList>
        <ForensicMarkFlagList><ForensicMarkFlag>http://www.smpte-ra.org/430-1/2006/KDM#mrkflg-audio-disable</ForensicMarkFlag></ForensicMarkFlagList>
      </KDMRequiredExtensions>
    </RequiredExtensions>
    <NonCriticalExtensions/>
  </AuthenticatedPublic>
  <AuthenticatedPrivate Id="ID_AuthenticatedPrivate"/>
</DCinemaSecurityMessage>
"""


def kdm(title, cpl_id, keys, screen, start, end):
    when = lambda t: t.isoformat(timespec="seconds")  # noqa: E731
    return KDM.format(
        message_id=uuid.uuid4(), title=title, screen=screen, screen_id=screen.replace(" ", "").lower(),
        issued=when(datetime.now(timezone.utc)), cpl_id=cpl_id, device_id=uuid.uuid4(),
        not_before=when(start), not_after=when(end),
        keys="".join(f"          <TypedKeyId><KeyType scope=\"http://www.smpte-ra.org/430-1/2006/KDM#kdm-key-type\">MDIK</KeyType><KeyId>urn:uuid:{k}</KeyId></TypedKeyId>\n" for k in keys),
    )


root = sys.argv[1] if len(sys.argv) > 1 else "sample-dcps"
out = sys.argv[2] if len(sys.argv) > 2 else "sample-kdms.zip"
now = datetime.now(timezone.utc).replace(microsecond=0)
day = timedelta(days=1)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for d in scanner.find_dcps(root):
        for cpl in scanner.read_cpls(d.path):
            if not cpl["key_ids"]:
                continue
            title, cpl_id, keys = cpl["title"], cpl["id"], cpl["key_ids"]
            short = d.name.split("_")[0]
            z.writestr(f"{short}/{short}_Salle1.xml", kdm(title, cpl_id, keys, "Salle 1", now - day, now + 7 * day))
            z.writestr(f"{short}/{short}_Salle2.xml", kdm(title, cpl_id, keys, "Salle 2", now - day, now + 7 * day))
            z.writestr(f"{short}/{short}_Salle3_expired.xml", kdm(title, cpl_id, keys, "Salle 3", now - 30 * day, now - 2 * day))
            z.writestr(f"{short}/{short}_Salle4_later.xml", kdm(title, cpl_id, keys, "Salle 4", now + 3 * day, now + 10 * day))
            z.writestr(f"{short}/{short}_Salle5_missing_key.xml", kdm(title, cpl_id, [uuid.uuid4()], "Salle 5", now - day, now + 7 * day))
            other = title.replace("_F_FR-XX_", "_F_EN-FR_")
            z.writestr(f"{short}/{short}_VOST_Salle1.xml", kdm(other, uuid.uuid4(), [uuid.uuid4()], "Salle 1", now - day, now + 7 * day))
    z.writestr("README.txt", "Fake KDMs made by dcpcheck's dev/make_sample_kdms.py.\n")
print("Sample KDMs written to", os.path.abspath(out))
