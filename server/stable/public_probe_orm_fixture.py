"""C026 独立本地 fixture，不提供生产授权或 proof。"""
from datetime import timedelta
from django.urls import reverse
from django.db import transaction
from stable import models as m
from stable.services.race_events import build_race_live_canonical_sha256


@transaction.atomic
def create_public_result_fixture(now):
    event = m.RaceEvent.objects.create(year=2026, slug="c026-local", original_name="C026 Local Stakes",
        country_region="united_kingdom", racecourse="Newbury", status="finished",
        visibility_status="published", race_datetime=now-timedelta(hours=1), local_date=now.date())
    # RaceEvent.save 已创建 canonical registry；不重复写入唯一路径。
    source = m.RaceResultSourceIdentity.objects.create(event=event, source_key="the_racing_api",
        external_race_id="c026-race", review_status="approved", terms_status="approved",
        automation_allowed=True, result_authority="supplemental", valid_until=now+timedelta(days=1), registry_digest="b"*64)
    for scope, key in (("global","global"),("region",event.country_region),("source",source.source_key),("event",str(event.pk))):
        m.RaceLivePublicationPolicy.objects.create(scope_type=scope,scope_key=key,mode="provisional_public",version=1,
            registry_digest="b"*64,coverage_proof_digest="c"*64,valid_until=now+timedelta(days=1))
    m.RaceLiveEventPublicationAllowlist.objects.create(event=event,source_key=source.source_key,
        max_mode="provisional_public",enabled=True,coverage_proof_digest="c"*64,
        official_verification_route="local-review",official_verification_route_version="local-v1",
        official_verification_valid_until=now+timedelta(days=1))
    payload={"external_race_id":source.external_race_id,"participants":[
        {"external_runner_id":f"c026-runner-{i}","official_finish_position":i,"status":"finished"} for i in (1,2)]}
    digest=build_race_live_canonical_sha256(normalized_payload=payload)
    observation=m.RaceResultObservation.objects.create(source_identity=source,observed_at=now-timedelta(minutes=1),
        parser_version="local-v1",raw_sha256="a"*64,normalized_sha256=digest,result_phase="provisional",
        normalized_payload=payload,raw_artifact_path="/forbidden/raw",permission_classification="local_fixture")
    revision=m.RaceEventRevision.objects.create(event=event,kind="result",revision_no=1,phase="provisional",
        content_sha256=digest,source_authority="supplemental",primary_observation=observation)
    m.RaceEventRevisionPublication.objects.create(revision=revision,published_at=now,reason="provisional_result",
        registry_digest="b"*64,coverage_proof_digest="c"*64,authorization_kind="provisional_policy",
        policy_versions=[[s,k,1] for s,k in (("global","global"),("region",event.country_region),("source",source.source_key),("event",str(event.pk)))])
    revision.published_at=now
    revision.save(update_fields=("published_at",))
    control=m.RaceEventProjectionControl.objects.create(event=event,write_owner="live",owner_generation=1,
        owner_manifest_sha256="d"*64,current_result_revision=revision,next_result_revision_no=2)
    for i in (1,2):
        participant=m.RaceEventParticipant.objects.create(event=event,stable_key=f"c026-{i}",canonical_name="Same Name",review_status="approved")
        m.RaceEventParticipantSourceIdentity.objects.create(participant=participant,source_identity=source,external_runner_id=f"c026-runner-{i}")
        m.RaceEventRevisionItem.objects.create(revision=revision,participant=participant,internal_order=i,
            official_finish_position=i,status="finished",horse_number=str(i),jockey_name=f"Local Jockey {i}")
        m.RaceEventResult.objects.create(event=event,finish_position=i,official_finish_position=i,
            horse_name=participant.canonical_name,horse_number=str(i),jockey_name=f"Local Jockey {i}",
            running_status="finished",is_confirmed=False,raw_payload={"secret":"DO_NOT_EXPORT"},source_refs={
                "source_key":source.source_key,"external_race_id":source.external_race_id,"external_runner_id":f"c026-runner-{i}"})
    return event,source,observation,revision,control,reverse("public-race-detail",kwargs={"year":2026,"slug":event.slug})
