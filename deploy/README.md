# deploy

The public server: one Azure VM running the same compose stack as a laptop, with Caddy in front for HTTPS.

| Piece | Choice |
| --- | --- |
| Account | Azure for Students, which a school email activates with no card |
| VM | `Standard_B2als_v2`, 2 vCPU, 4 GB, Ubuntu 24.04, 30 GB Standard SSD, in `francecentral` |
| Network | the VM's own security group, inbound 22, 80 and 443 |
| Name | `atlasofdoubt.francecentral.cloudapp.azure.com`, the public IP's free Azure DNS label |
| HTTPS | Caddy 2.10.2 and Let's Encrypt, from [`compose.yml`](compose.yml) |
| Writes | each client saves at most 20 reports an hour |

The student subscription allows five regions only: `italynorth`, `polandcentral`, `norwayeast`, `francecentral` and `spaincentral`.

## Create the VM

A separate `AZURE_CONFIG_DIR` keeps the school login apart from any other Azure account on the same machine.

```bash
export AZURE_CONFIG_DIR=~/.azure-school && az login --use-device-code
```

```bash
az group create -n atlas-rg -l francecentral
```

```bash
az vm create -g atlas-rg -n atlas --image Canonical:ubuntu-24_04-lts:server:latest --size Standard_B2als_v2 --admin-username atlas --ssh-key-values ~/.ssh/id_ed25519.pub --public-ip-sku Standard --storage-sku StandardSSD_LRS --os-disk-size-gb 30
```

```bash
az vm open-port -g atlas-rg -n atlas --port 80,443 --priority 900
```

```bash
az network public-ip update -g atlas-rg -n atlasPublicIP --dns-name atlasofdoubt
```

## On the VM

```bash
curl -fsSL https://get.docker.com | sudo sh
```

The app's warm-up rebuilds the last visited countries at boot. Without swap that filled the 4 GB and froze the VM, SSH included. Now the VM has 4 GB of swap, and [`compose.yml`](compose.yml) caps each container's memory and the app's CPU.

```bash
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Compose rotates container logs at 30 MB each. The journal stops at 200 MB, and a weekly job drops images and build cache unused for a week. Volumes and `data/` are never touched.

```bash
sudo sed -i 's/^#\?SystemMaxUse=.*/SystemMaxUse=200M/' /etc/systemd/journald.conf && sudo systemctl restart systemd-journald
```

```bash
printf '#!/bin/sh\ndocker image prune -af --filter until=168h\ndocker builder prune -af --filter until=168h\n' | sudo tee /etc/cron.weekly/docker-prune && sudo chmod +x /etc/cron.weekly/docker-prune
```

```bash
git clone https://github.com/ReguiguiMohamed/AtlasOfDoubt && cd AtlasOfDoubt
```

## Data

CEPII answers 403 to Azure addresses, so the VM can't download BACI. A laptop that already ran `atlas.prepare` sends the prepared snapshot and its MongoDB documents instead.

```bash
python -m deploy.dump BACI_HS12_V202601@537b2fe453e3
```

That writes `data/snapshots/mongo-dump/atlas/*.bson.gz`, 166 MB for this snapshot. Copy it and `data/snapshots/BACI_HS12_V202601@537b2fe453e3/`, 1.05 GB, to the same paths on the VM. Parallel `tar` streams over SSH beat one stream on a slow uplink.

## Start

Compose reads the name from `.env`, so later commands and reboots need no export.

```bash
echo ATLAS_HOST=atlasofdoubt.francecentral.cloudapp.azure.com > .env
```

```bash
sudo docker compose -f docker-compose.yml -f deploy/compose.yml up --build -d
```

```bash
sudo docker compose exec mongo mongorestore --gzip --dir /dump
```

The app creates its indexes on the next start.

```bash
sudo docker compose -f docker-compose.yml -f deploy/compose.yml restart app
```
