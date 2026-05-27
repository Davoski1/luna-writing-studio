# Azure Student Deployment Manual: Zero-Dollar Launch

This manual provides the step-by-step configuration required to deploy the **Luna AI Writing Studio** onto Microsoft Azure. By utilizing your **Azure for Students** free allocations, the hosting, database, and asset storage will cost **$0.00/month**.

---

## 🏗️ 1. Create your Resource Group
1. Log in to the [Azure Portal](https://portal.azure.com).
2. Click **Create a resource** and search for **Resource Group**.
3. Name it `luna-writing-studio-rg`.
4. Select your preferred region (e.g., `East US` or `West US`) and click **Review + Create**.

---

## 💾 2. Deploy your Free PostgreSQL Flexible Server
1. Search for **Azure Database for PostgreSQL** in the Portal search bar.
2. Click **Create** and select **Flexible Server**.
3. Set the following configuration details:
   * **Server name**: `luna-writing-db` (must be unique).
   * **Compute + storage**: Click **Configure server**.
     * Select **Burstable** compute.
     * Select **Standard_B1ms** shape (1 vCPU, 2 GB RAM) — *this is the student free tier*.
     * Under **Storage size**, select exactly **32 GB** (do NOT enable storage auto-grow).
     * Click **Save**.
   * **Authentication**: Set an admin username and a strong password. Record these.
4. Go to the **Networking** tab:
   * Check the box for **Allow public access from any Azure service within Azure**. (This permits your API server to connect securely).
   * Add a firewall rule for your local IP address to allow database configuration migrations.
5. Click **Review + Create**.

---

## 📦 3. Deploy your Free Azure Blob Storage
1. Search for **Storage Accounts** in the Portal search bar.
2. Click **Create** and configure:
   * **Performance**: Standard.
   * **Redundancy**: Locally-redundant storage (LRS) — *this is the lowest cost/free tier*.
3. Once deployed, open the Storage Account pane:
   * Navigate to **Security + networking** -> **Access keys**.
   * Copy the **Connection string** (Record this as `AZURE_STORAGE_CONNECTION_STRING`).
   * Navigate to **Data storage** -> **Containers** and create a container named `novels`.

---

## 🚀 4. Host your Backend on a Free B1s VM
1. Search for **Virtual Machines** and click **Create** -> **Azure virtual machine**.
2. Configure:
   * **Image**: `Ubuntu Server 22.04 LTS - Gen2`.
   * **Size**: **Standard_B1s** (1 vCPU, 1 GB RAM) — *this is the student free VM allocation*.
   * **Inbound port rules**: Allow `SSH (22)`, `HTTP (80)`, and `HTTPS (443)`.
   * **OS Disk Type**: Set to **Standard SSD** or **Standard HDD** with size exactly **30 GB**.
3. Once booted, SSH into your virtual machine and install the docker container engine:
   ```bash
   sudo apt-get update
   sudo apt-get install -y docker.io git
   ```
4. Clone your repository or copy your code to the VM:
   ```bash
   git clone <your-repo-link>
   cd writing_agent
   ```
5. Run the docker container, passing your Azure B-series environment variables:
   ```bash
   sudo docker build -t writing-api .
   
   sudo docker run -d -p 80:80 \
     -e DATABASE_URL="postgresql://<admin_user>:<password>@luna-writing-db.postgres.database.azure.com:5432/postgres?sslmode=require" \
     -e AZURE_STORAGE_CONNECTION_STRING="<your_copied_storage_connection_string>" \
     -e AZURE_STORAGE_CONTAINER="novels" \
     -e AZURE_OPENAI_ENDPOINT="<your_azure_openai_endpoint>" \
     -e AZURE_OPENAI_KEY="<your_azure_openai_key>" \
     -e API_MODEL="gpt-4o-mini" \
     --name luna-backend writing-api
   ```

---

## 🖥️ 5. Deploy the React Frontend to Static Web Apps (Free Tier)
1. Search for **Static Web Apps** in the Portal search bar.
2. Click **Create** and choose **Free: For hobby or personal projects** pricing tier.
3. Link your GitHub repository and point the build configuration to your `frontend` directory.
4. Once deployed, Azure will generate a URL like `https://xxx.azurestaticapps.net`.
5. Add this SWA URL to the `FRONTEND_URL` environment variable inside your backend container to allow CORS communication.
