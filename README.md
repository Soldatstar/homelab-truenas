# TrueNAS Homelab Documentation & Monitoring

This repository is a collection of notes, documentation, and monitoring dashboards for my **TrueNAS setup**.
It’s part of my homelab and also a way to **showcase my approach to storage management, backups, and monitoring**.

![TrueNas Health](https://healthchecks.io/b/2/3d3498ca-52ea-4d00-8a15-0bd876f54698.svg)
![TrueNas-PrimaryBackup](https://healthchecks.io/b/2/3c02cfdd-3423-464a-8337-248d5f697273.svg)
![TrueNas-SecondaryBackup](https://healthchecks.io/b/2/4233cdb4-8d9f-4b7c-a07b-9a627e52bac5.svg)
![TrueNas-Configs](https://healthchecks.io/b/2/5fecd766-d83e-4370-90dd-39dbdba44df4.svg)

---

## 🌐 Overview

I run a self-hosted **TrueNAS server** that handles:

* File storage for personal data & media for me and my immediate family
* Automated backups (local + remote)
* Monitoring and health checks with [Healthchecks.io](https://healthchecks.io)

This repo contains:

* Documentation of my setup (hardware, configuration, and backup strategies)
* Scripts I use for automation

---

## 🖥️ Server Specs

* **CPU:** AMD Ryzen 7 1700 (8 cores / 16 threads)
* **GPU:** NVIDIA Quadro P2000 (hardware-accelerated media transcoding)
* **Memory:** 48 GB DDR4 (non-ECC)

**Storage Layout**

* **Application Pool (AppPool):** 2 × 1 TB Kingston KC600 SSDs in mirror

  * Hosts configuration files and workloads that benefit from SSD speed.
  * Serves as storage for **virtual machines**.
  * Selected configuration data from this pool is included in offsite backups.

* **Storage Pool 1 – Critical Data:** 2 × 4 TB Seagate SkyHawk HDDs in mirror

  * Dedicated to important files.
  * This pool is **fully included in offsite backups**.

* **Storage Pool 2 – Media (Bulk, Non-Critical):** RAIDZ1 with 4 × 4 TB Seagate IronWolf HDDs

  * 16 TB raw capacity → \~12 TB usable.
  * Used for large media files and non-critical data.

* **Storage Pool 3 – Media (Bulk, Non-Critical):** RAIDZ1 with 3 × 6 TB Toshiba N300 NAS HDDs

  * 18 TB raw capacity → \~12 TB usable.
  * Also used for large, non-critical media files.

* **OS:** TrueNAS SCALE
---

## 🗂️ Services - summary

Below is a short, high-level summary of the **types of services** I host on the TrueNAS homelab. I kept it focused and recruiter-friendly - no credentials or sensitive details are included here.

**Core / Infrastructure**

* TrueNAS (host and storage management)
* Nginx / Nginx Proxy Manager for reverse proxying and SSL termination
* Routers / network equipment (local gateway + ISP router)

**Monitoring & Notifications**

* Healthchecks.io for monitoring scheduled jobs and backup pings (badges shown above)
* Glances (system metrics widgets) for CPU / RAM / temperature / network
* Gotify for push notifications

**Media & Streaming**

* Media server (Jellyfin) for family streaming
* Torrent client (qBittorrent) and associated download automation (Sonarr / Radarr for TV/movies; Lidarr for music)
* Media helpers: Bazarr for subtitles, Jellyseerr for media discovery

**Personal Cloud & Photos**

* Nextcloud for files and syncing
* Immich for photo/video backup and management

**Audio**

* Navidrome for streaming personal music libraries
* Lidarr for music library management

**Security & IDS**

* CrowdSec for intrusion detection / machine-level hardening
* Pi-hole instances for DNS-level ad-blocking on the network

**Documents & Productivity**

* Paperless (document OCR/archiving)
* (planned/optional): Bookstack / Vaultwarden / Linkwarden-like services for documentation and password management

**Home Automation / Cameras / Events**

* Frigate for camera/event detection and recording
* Calendar widget aggregating personal calendar plus *arr* stack events for upcoming downloads/episodes

---

## 🔄 Backup & Sync

Backups are done using `rsync` over SSH to multiple remote StorageBoxex.

* Daily scheduled syncs
* Logs stored locally and rotated weekly
* Monitored with Healthchecks.io

---

## ✅ Monitoring

This project uses [Healthchecks.io](https://healthchecks.io) to monitor backup jobs and critical services.
If a job doesn’t run or fails, I get notified.

---

## 📚 Why this Repo?

* To keep **clear documentation** of my setup for myself
* To **demonstrate infrastructure & monitoring skills** on my CV
* To share ideas with others running homelabs

---

## 🚀 Skills Demonstrated

* Linux server administration
* TrueNAS configuration & storage management
* Backup automation with `rsync`
* Monitoring & alerting integration
* Writing clean documentation

---

## 📌 Next Steps

* Add screenshots of TrueNAS dashboards
* Expand Monitoring/Logging/Alerting
* Expand documentation for restore/testing procedures
* Create a clean file structure

