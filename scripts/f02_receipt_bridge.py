"""Root/R receipt bridge; trusted_reader is supplied by the existing authenticated root call surface.

No CLI, identity provisioning, external calls or persistent key. Files/issuer strings are not R authentication.
"""
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path

from scripts import f02_transfer as transfer
from scripts import f02_readonly_export as export

class BridgeError(ValueError):
    pass

def require(value):
    if not value:
        raise BridgeError('R_origin_binding_rejected')

def deliver(capsule, artifact_root, origin, *, trusted_reader, trusted_R_thread, source_metadata_dir=None):
    """The trusted reader must fetch actual message origin metadata, not deserialize a producer file.

    A package review is insufficient. The returned payload must explicitly describe an independently received package.
    """
    try:
        require(callable(trusted_reader) and isinstance(trusted_R_thread,str) and bool(trusted_R_thread))
        keys={'thread_id','turn_id','message_id','payload_sha256'}
        require(isinstance(origin,dict) and set(origin)==keys and origin['thread_id']==trusted_R_thread)
        require(all(isinstance(origin[key],str) and transfer.NAME.fullmatch(origin[key]) for key in ('thread_id','turn_id','message_id')))
        require(transfer.HASH.fullmatch(origin['payload_sha256']))
        message=trusted_reader(thread_id=origin['thread_id'],turn_id=origin['turn_id'],message_id=origin['message_id'])
        require(isinstance(message,dict) and set(message)==keys|{'payload'}
                and all(message[key]==origin[key] for key in keys))
        ack=message['payload']
        expected={'schema_version','issuer','capsule_sha256','manifest_sha256','observation_id','received_at','artifact_received'}
        require(isinstance(ack,dict) and set(ack)==expected and ack['artifact_received'] is True and ack['schema_version']==1
                and ack['issuer']=='R' and ack['capsule_sha256']==transfer.capsule_sha(capsule)
                and ack['manifest_sha256']==capsule['manifest_sha256'] and ack['observation_id']==capsule['observation_id'])
        require(export.digest(export.encoded(ack))==origin['payload_sha256'])
        require(datetime.fromisoformat(ack['received_at']).tzinfo is not None)
        root=transfer.private_directory(artifact_root)
        home=transfer.private_directory(root/transfer.capsule_sha(capsule))
        # Separate control lock; host inspector and record_delivery own their artifact lock independently.
        control=transfer.mkdir_private(home/'trusted-receipt-control')
        with transfer.artifact_lock(control):
            transfer.inspect_host(capsule,root,source_metadata_dir)
            source={'schema_version':1,**origin,'capsule_sha256':transfer.capsule_sha(capsule),
                    'manifest_sha256':capsule['manifest_sha256'],'observation_id':capsule['observation_id']}
            source_path=home/'R.source.json'
            if source_path.exists():
                require(transfer.parse(transfer.read_file(source_path,65536))==source)
            else:
                transfer.atomic_json(source_path,source)
            received=home/'R.received'
            if received.exists():
                prior=transfer.parse(transfer.read_file(received,65536))
                require(prior.get('state')=='delivered_to_R' and prior.get('issuer')=='R'
                        and all(prior.get(key)==ack[key] for key in ('capsule_sha256','manifest_sha256','observation_id','received_at')))
                return prior
            # Short-lived bridge material only, not the evidence of R identity (which was verified above).
            key=bytearray(os.urandom(32))
            try:
                signed={k:v for k,v in ack.items() if k!='artifact_received'}
                signed['signature']=hmac.new(bytes(key),export.encoded(signed),hashlib.sha256).hexdigest()
                return transfer.record_delivery(capsule,root,signed,r_key=bytes(key),source_metadata_dir=source_metadata_dir)
            finally:
                key[:]=b'\0'*len(key)  # best-effort lifetime reduction; no promise of Python memory erasure
    except BridgeError:
        raise
    except Exception:
        raise BridgeError('R_bridge_failed') from None
