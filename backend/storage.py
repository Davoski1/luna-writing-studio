import os
from datetime import datetime, timedelta

AZURE_STORAGE_CONN = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
CONTAINER_NAME = os.getenv("AZURE_STORAGE_CONTAINER", "novels")

def upload_to_azure_blob(local_file_path, file_name):
    """
    Uploads a compiled book (PDF or HTML) to Azure Blob Storage
    if a connection string is active. Returns the public secure URL,
    otherwise falls back to local routing (returning None).
    """
    if not AZURE_STORAGE_CONN:
        print("[Storage] Connection string missing; serving file locally.")
        return None

    try:
        from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
        
        # Initialize Client
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONN)
        
        # Create container if it doesn't exist
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        try:
            container_client.create_container()
            print(f"[Storage] Created container '{CONTAINER_NAME}' on Azure.")
        except Exception:
            # Container already exists
            pass

        # Get blob client and upload
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=file_name)
        with open(local_file_path, "rb") as data:
            blob_client.upload_blob(data, overwrite=True)
        print(f"[Storage] Successfully uploaded {file_name} to Azure Blob Storage.")

        # Generate a secure SAS token valid for 2 hours
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=CONTAINER_NAME,
            blob_name=file_name,
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=2)
        )
        
        blob_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{CONTAINER_NAME}/{file_name}?{sas_token}"
        return blob_url
        
    except Exception as e:
        print(f"[Storage Error] Failed to upload to Azure: {e}")
        return None
