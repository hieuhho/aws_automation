import json, os, time, random, string, re, urllib.request, urllib.error
import boto3
from botocore.exceptions import ClientError

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
SLACK_SECRET_ARN = os.getenv("SLACK_SECRET_ARN")
BUCKET_PREFIX = os.getenv("BUCKET_PREFIX", "learn")

s3 = boto3.client("s3", region_name=AWS_REGION)
secrets = boto3.client("secretsmanager", region_name=AWS_REGION)
_slack_cache = None  # reused across warm invocations

BUCKET_RE = re.compile(r"^(?!\d+\.\d+\.\d+\.\d+$)[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")

def _rand(n=8): return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

def _valid_bucket(name: str) -> bool:
    return bool(name) and 3 <= len(name) <= 63 and BUCKET_RE.match(name) and "_" not in name and ".." not in name and ".-" not in name and "-." not in name

def _load_slack():
    global _slack_cache
    if _slack_cache is not None:
        return _slack_cache
    if not SLACK_SECRET_ARN:
        return None
    val = secrets.get_secret_value(SecretId=SLACK_SECRET_ARN)["SecretString"]
    obj = json.loads(val) if val and val.strip().startswith("{") else {"bot_token": val}
    _slack_cache = {"token": obj["bot_token"], "channel": obj.get("channel")}
    return _slack_cache

def _notify_slack(text: str, channel_override: str | None = None):
    info = _load_slack()
    if not info:
        print("Slack not configured; skipping.")
        return
    token = info["token"]; channel = channel_override or info.get("channel")
    if not token or not channel:
        print("Missing token or channel; skipping Slack.")
        return
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": channel, "text": text}).encode("utf-8"),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read() or b"{}")
            if not body.get("ok"):
                print(f"Slack error: {body}")
    except urllib.error.URLError as e:
        print(f"Slack request failed: {e}")

def _create_bucket(name: str, region: str):
    client = boto3.client("s3", region_name=region)
    if region == "us-east-1":
        client.create_bucket(Bucket=name)
    else:
        client.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": region})
    # sensible defaults
    client.put_public_access_block(
        Bucket=name, PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True
        }
    )
    client.put_bucket_encryption(
        Bucket=name, ServerSideEncryptionConfiguration={
            "Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]
        }
    )
    client.put_bucket_tagging(Bucket=name, Tagging={"TagSet":[{"Key":"owner","Value":"automation"},{"Key":"env","Value":"prod"}]})

def _destroy_bucket(name: str, region: str):
    client = boto3.client("s3", region_name=region)
    # empty versioned bucket
    paginator = client.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=name):
        dels = []
        for v in page.get("Versions", []):
            dels.append({"Key": v["Key"], "VersionId": v["VersionId"]})
        for m in page.get("DeleteMarkers", []):
            dels.append({"Key": m["Key"], "VersionId": m["VersionId"]})
        if dels:
            client.delete_objects(Bucket=name, Delete={"Objects": dels})
    # handle non-versioned just in case
    paginator2 = client.get_paginator("list_objects_v2")
    for page in paginator2.paginate(Bucket=name):
        objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objs:
            client.delete_objects(Bucket=name, Delete={"Objects": objs})
    client.delete_bucket(Bucket=name)

def _default_name(user_hint: str | None, region: str) -> str:
    today = time.strftime("%Y%m%d")
    base = re.sub(r"[^a-z0-9-]", "-", (user_hint or "bucket")).strip("-").lower()
    base = re.sub(r"-+", "-", base) or "bucket"
    name = f"{BUCKET_PREFIX}-{base}-{region}-{today}-{_rand(6)}"
    return name[:63].rstrip("-")

def handler(event, context):
    """
    event = {
      "action": "create"|"destroy",
      "name": "bucket-name" (optional for create),
      "user": "display name hint" (optional),
      "region": "us-east-1" (optional),
      "notify": true/false,
      "slack_channel": "#devops" or "C0123" (optional)
    }
    """
    action = (event.get("action") or "create").lower()
    region = event.get("region") or AWS_REGION

    if action == "create":
        name = event.get("name") or _default_name(event.get("user"), region)
        if not _valid_bucket(name):
            return {"ok": False, "error": f"invalid_bucket_name:{name}"}
        try:
            _create_bucket(name, region)
            if event.get("notify"):
                _notify_slack(f":white_check_mark: S3 bucket *{name}* created in `{region}`.", event.get("slack_channel"))
            return {"ok": True, "bucket": name, "region": region}
        except ClientError as e:
            return {"ok": False, "error": str(e)}
    elif action == "destroy":
        name = event.get("name")
        if not name or not _valid_bucket(name):
            return {"ok": False, "error": "name_required"}
        try:
            _destroy_bucket(name, region)
            if event.get("notify"):
                _notify_slack(f":wastebasket: S3 bucket *{name}* deleted from `{region}`.", event.get("slack_channel"))
            return {"ok": True, "bucket": name, "region": region}
        except ClientError as e:
            return {"ok": False, "error": str(e)}
    else:
        return {"ok": False, "error": "unknown_action"}
