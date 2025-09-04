import os
from datetime import datetime
import argparse, logging, random, string
import boto3
import dotenv
from botocore.exceptions import ClientError
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
dotenv.load_dotenv()


def rand_suffix(n=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

def create_bucket(bucket_name: str, region: str = "us-east-1") -> bool:
    s3 = boto3.client("s3", region_name=region)
    try:
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        print(f"✅ created: {bucket_name} in {region}")
        return True
    except ClientError as e:
        logging.error(e)
        return False

def destroy_bucket(bucket_name: str, region: str = "us-east-1") -> bool:
    s3 = boto3.client("s3", region_name=region)
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket_name):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                s3.delete_objects(Bucket=bucket_name, Delete={"Objects": objs})
        s3.delete_bucket(Bucket=bucket_name)
        logging.info(f"deleted: {bucket_name}")
        return True
    except ClientError as e:
        logging.error(e)
        return False

def notify_slack(bucket: str, region: str, channel: str | None = None) -> None:
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = channel or os.getenv("SLACK_CHANNEL")
    print("channel", channel)
    if not token or not channel:
        print("⚠️  Slack not configured (SLACK_BOT_TOKEN/SLACK_CHANNEL). Skipping.")
        return
    try:
        WebClient(token=token).chat_postMessage(
            channel=channel,
            text=f":white_check_mark: S3 bucket *{bucket}* created in `{region}`."
        )
        print("✅ Slack notified")
    except SlackApiError as e:
        print(f"❌ Slack notify failed: {e}")

def parse_args():
    p = argparse.ArgumentParser(description="Create/Destroy S3 buckets.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="Create an S3 bucket")
    c.add_argument("-n", "--name", metavar="", help="Bucket name (globally unique). If omitted, generates one.")
    c.add_argument("-r", "--region", default="us-east-1", metavar="", help="Region (default: us-east-1)")
    c.add_argument("--notify", action="store_true", help="Send Slack message after create")
    c.add_argument("--slack-channel", help="Override Slack channel (e.g. #devops or C0123456789)")


    d = sub.add_parser("destroy", help="Delete an S3 bucket")
    d.add_argument("-n", "--name", required=True, metavar="", help="Bucket name to delete")
    d.add_argument("-r", "--region", default="us-east-1", metavar="", help="Region (default: us-east-1)")
    return p.parse_args()

def main():
    args = parse_args()
    if args.cmd == "create":
        name = args.name or f"hieu-{datetime.now().strftime('%Y%m%d')}-{rand_suffix()}"
        ok = create_bucket(name, args.region)
        if ok:
            print(name)  # echo for scripting
            if getattr(args, "notify", False):
                notify_slack(name, args.region, channel=getattr(args, "slack_channel", None))

    elif args.cmd == "destroy":
        destroy_bucket(args.name, args.region)

if __name__ == "__main__":
    main()
