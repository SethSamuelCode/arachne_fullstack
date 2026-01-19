from boto3 import client

from app.core.config import settings

S3_ENDPOINT = settings.S3_ENDPOINT
S3_ACCESS_KEY = settings.S3_ACCESS_KEY
S3_SECRET_KEY = settings.S3_SECRET_KEY
S3_BUCKET = settings.S3_BUCKET


class s3Service:
    def __init__(self):
        self.s3_client = client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
        )
        # create the bucket if it doesn't exist
        existing_buckets = self.s3_client.list_buckets()
        if not any(bucket["Name"] == S3_BUCKET for bucket in existing_buckets.get("Buckets", [])):
            self.s3_client.create_bucket(Bucket=S3_BUCKET)

    def upload_file(self, file_name: str, object_name: str) -> None:
        """Upload a file to an S3 bucket

        :param file_name: File to upload
        :param object_name: S3 object name. If not specified then file_name is used
        :return: True if file was uploaded, else False
        """
        try:
            self.s3_client.upload_file(file_name, S3_BUCKET, object_name)
        except Exception as e:
            print(f"Error uploading file to S3: {e}")
            raise e

    def download_file(self, object_name: str, file_name: str) -> None:
        """Download a file from an S3 bucket

        :param object_name: S3 object name
        :param file_name: File to download to
        :return: True if file was downloaded, else False
        """
        try:
            self.s3_client.download_file(S3_BUCKET, object_name, file_name)
        except Exception as e:
            print(f"Error downloading file from S3: {e}")
            raise e

    def upload_obj(self, obj_data: bytes, object_name: str) -> None:
        """Upload an object to an S3 bucket

        :param obj_data: Object data to upload
        :param object_name: S3 object name
        :return: True if object was uploaded, else False
        """
        try:
            self.s3_client.put_object(Bucket=S3_BUCKET, Key=object_name, Body=obj_data)
        except Exception as e:
            print(f"Error uploading object to S3: {e}")
            raise e

    def download_obj(self, object_name: str) -> bytes:
        """Download an object from an S3 bucket

        :param object_name: S3 object name
        :return: Object data
        """
        try:
            response = self.s3_client.get_object(Bucket=S3_BUCKET, Key=object_name)
            return response["Body"].read()
        except Exception as e:
            print(f"Error downloading object from S3: {e}")
            raise e

    def delete_obj(self, object_name: str) -> None:
        """Delete an object from an S3 bucket

        :param object_name: S3 object name
        :return: True if object was deleted, else False
        """
        try:
            self.s3_client.delete_object(Bucket=S3_BUCKET, Key=object_name)
        except Exception as e:
            print(f"Error deleting object from S3: {e}")
            raise e

    def list_objs(self, prefix: str | None = None) -> list[str]:
        """List objects in an S3 bucket

        :param prefix: Optional prefix to filter objects
        :return: List of object names
        """
        try:
            params: dict = {"Bucket": S3_BUCKET}
            if prefix:
                params["Prefix"] = prefix
            response = self.s3_client.list_objects_v2(**params)
            if "Contents" in response:
                return [item["Key"] for item in response["Contents"]]
            else:
                return []
        except Exception as e:
            print(f"Error listing objects in S3: {e}")
            raise e

    def list_objs_with_metadata(self, prefix: str | None = None) -> list[dict]:
        """List objects in an S3 bucket with metadata

        :param prefix: Optional prefix to filter objects
        :return: List of dicts with key, size, last_modified, content_type
        """
        try:
            params: dict = {"Bucket": S3_BUCKET}
            if prefix:
                params["Prefix"] = prefix
            response = self.s3_client.list_objects_v2(**params)
            if "Contents" in response:
                return [
                    {
                        "key": item["Key"],
                        "size": item["Size"],
                        "last_modified": item["LastModified"],
                        "content_type": item.get("ContentType"),
                    }
                    for item in response["Contents"]
                ]
            else:
                return []
        except Exception as e:
            print(f"Error listing objects in S3: {e}")
            raise e

    def generate_presigned_download_url(self, object_name: str, expiration: int = 3600) -> str:
        """Generate a presigned URL to share an S3 object

        :param object_name: S3 object name
        :param expiration: Time in seconds for the presigned URL to remain valid
        :return: Presigned URL as string. If error, returns None.
        """
        try:
            response = self.s3_client.generate_presigned_url(
                "get_object", Params={"Bucket": S3_BUCKET, "Key": object_name}, ExpiresIn=expiration
            )
        except Exception as e:
            print(f"Error generating presigned URL for S3 object: {e}")
            raise e
        return response

    def generate_presigned_post(self, object_name: str, expiration: int = 3600) -> dict:
        """Generate a presigned POST to share an S3 object

        :param object_name: S3 object name
        :param expiration: Time in seconds for the presigned POST to remain valid
        :return: Presigned POST as dict with 'url' and 'fields' keys.
        """
        try:
            response = self.s3_client.generate_presigned_post(
                Bucket=S3_BUCKET, Key=object_name, ExpiresIn=expiration
            )
        except Exception as e:
            print(f"Error generating presigned POST for S3 object: {e}")
            raise e
        return response

    def generate_presigned_posts_batch(
        self, object_names: list[str], expiration: int = 3600
    ) -> list[dict]:
        """Generate presigned POST URLs for multiple S3 objects.

        :param object_names: List of S3 object names
        :param expiration: Time in seconds for the presigned POSTs to remain valid
        :return: List of presigned POST dicts with 'url' and 'fields' keys.
        """
        results = []
        for object_name in object_names:
            try:
                response = self.s3_client.generate_presigned_post(
                    Bucket=S3_BUCKET, Key=object_name, ExpiresIn=expiration
                )
                results.append(response)
            except Exception as e:
                print(f"Error generating presigned POST for S3 object {object_name}: {e}")
                raise e
        return results

    def copy_file(self, source_object_name: str, dest_object_name: str) -> None:
        """Copy a file within an S3 bucket

        :param source_object_name: Source S3 object name
        :param dest_object_name: Destination S3 object name
        :return: True if file was copied, else False
        """
        try:
            copy_source = {"Bucket": S3_BUCKET, "Key": source_object_name}
            self.s3_client.copy(copy_source, S3_BUCKET, dest_object_name)
        except Exception as e:
            print(f"Error copying file in S3: {e}")
            raise e

    def presigned_download_url(self, object_name: str, expiration: int = 3600) -> str:
        """Generate a presigned URL to download an S3 object

        :param object_name: S3 object name
        :param expiration: Time in seconds for the presigned URL to remain valid
        :return: Presigned URL as string. If error, returns None.
        """
        try:
            response = self.s3_client.generate_presigned_url(
                "get_object", Params={"Bucket": S3_BUCKET, "Key": object_name}, ExpiresIn=expiration
            )
        except Exception as e:
            print(f"Error generating presigned download URL for S3 object: {e}")
            raise e
        return response


s3_service = s3Service()


def get_s3_service():
    return s3_service
