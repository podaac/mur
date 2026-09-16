#!/home/tmchin/python_envs/mur/bin/python

# Standard imports
import pathlib
import sys

# Third-party imports
import boto3
import botocore

def upload(s3_bucket, dataset_key, filename):
    """Upload file found at filename path to S3 bucket."""
    
    filename_path = pathlib.Path(filename)
    session = boto3.Session(profile_name="SRV-podaac-dev-ghrsst-jpl")
    s3_client = session.client("s3")
    try:
        response = s3_client.upload_file(filename, s3_bucket, f"{dataset_key}/{filename_path.name}", ExtraArgs={"ServerSideEncryption": "AES256"})
        print(f"File uploaded: s3://{s3_bucket}/{dataset_key}/{filename_path.name}.")
    except botocore.exceptions.ClientError as e:
        print(f"Error encoutered: {e}.")
        print(f"{filename} was not uploaded. Continuing execution.")
            
if __name__ == "__main__":
    
    s3_bucket = sys.argv[1]
    dataset_key = sys.argv[2]
    filename = sys.argv[3]
    upload(s3_bucket, dataset_key, filename)
            