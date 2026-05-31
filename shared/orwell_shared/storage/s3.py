from __future__ import annotations


class S3StorageBackend:
    def __init__(self, bucket: str, prefix: str = "", client=None):
        self.bucket = bucket
        self.prefix = prefix
        if client is None:
            import boto3  # import tardio: só quando realmente usar S3

            client = boto3.client("s3")
        self.client = client

    def put(self, local_path: str, key: str, metadata: dict) -> str:
        full_key = f"{self.prefix}{key}"
        self.client.upload_file(
            Filename=local_path, Bucket=self.bucket, Key=full_key,
            ExtraArgs={"Metadata": {k: str(v) for k, v in metadata.items()}},
        )
        return f"s3://{self.bucket}/{full_key}"
