import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import f02_receipt_bridge as bridge
from scripts import f02_transfer as transfer
from scripts import f02_readonly_export as export
from scripts.tests.test_f02_transfer import fixture, FakeAdapter

class BridgeTests(unittest.TestCase):
    def prepare(self, base):
        directory, capsule, _ = fixture(base)
        root = base.resolve()/'host'
        transfer.transfer(capsule, root, FakeAdapter(directory,capsule),'attempt1',disk_free=lambda _:10**10)
        # R independently opens the actual fixed package and hashes its manifest.
        final=root/transfer.capsule_sha(capsule)/'runtime/next_version/F02'/capsule['observation_id']
        transfer.verify_bundle(final,capsule)
        ack={'schema_version':1,'issuer':'R','capsule_sha256':transfer.capsule_sha(capsule),
             'manifest_sha256':hashlib.sha256((final/'manifest.json').read_bytes()).hexdigest(),
             'observation_id':capsule['observation_id'],'received_at':'2026-10-03T00:00:00+00:00',
             'artifact_received':True}
        origin={'thread_id':'R-original-thread','turn_id':'R-fixed-turn','message_id':'R-received-message',
                'payload_sha256':export.digest(export.encoded(ack))}
        message={**origin,'payload':ack}
        return capsule,root,origin,message

    def test_missing_or_wrong_origin_cannot_be_self_signed(self):
        with tempfile.TemporaryDirectory() as temp:
            capsule,root,origin,message=self.prepare(Path(temp))
            message['thread_id']='producer-thread'
            with self.assertRaises(bridge.BridgeError):
                bridge.deliver(capsule,root,origin,trusted_reader=lambda **kw:message,trusted_R_thread='R-original-thread')
            self.assertFalse((root/transfer.capsule_sha(capsule)/'R.received').exists())

    def test_received_provenance_is_bound_and_idempotent_without_saved_key(self):
        with tempfile.TemporaryDirectory() as temp:
            capsule,root,origin,message=self.prepare(Path(temp))
            keys=[]
            real=transfer.record_delivery
            def record(*args,**kwargs):
                keys.append(kwargs['r_key'])
                return real(*args,**kwargs)
            with patch.object(transfer,'record_delivery',side_effect=record):
                first=bridge.deliver(capsule,root,origin,trusted_reader=lambda **kw:message,trusted_R_thread='R-original-thread')
                again=bridge.deliver(capsule,root,origin,trusted_reader=lambda **kw:message,trusted_R_thread='R-original-thread')
            self.assertEqual(first['state'],'delivered_to_R')
            self.assertEqual(first,again)
            self.assertEqual(len(keys),1)
            for file in root.rglob('*'):
                if file.is_file():
                    self.assertNotIn(keys[0],file.read_bytes())
            self.assertTrue((root/transfer.capsule_sha(capsule)/'R.source.json').exists())

    def test_wrong_package_or_review_without_receipt_is_rejected(self):
        for field,value in [('manifest_sha256','f'*64),('artifact_received',False),('issuer','producer')]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temp:
                capsule,root,origin,message=self.prepare(Path(temp))
                message['payload'][field]=value
                # Even a correctly committed trusted message must bind the actual package.
                origin['payload_sha256']=export.digest(export.encoded(message['payload']))
                message['payload_sha256']=origin['payload_sha256']
                with self.assertRaises(bridge.BridgeError):
                    bridge.deliver(capsule,root,origin,trusted_reader=lambda **kw:message,trusted_R_thread='R-original-thread')
                self.assertFalse((root/transfer.capsule_sha(capsule)/'R.received').exists())
