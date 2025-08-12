# Docker Proxy Configuration Solutions

## Option 1: Configure Docker Desktop Proxy Settings

1. Open Docker Desktop
2. Go to Settings → Resources → Proxies
3. Enable "Manual proxy configuration"
4. Set HTTP proxy: http://wired.meraki.com:8090
5. Set HTTPS proxy: http://wired.meraki.com:8090
6. Add to bypass list: localhost,127.0.0.1
7. Apply & Restart Docker

## Option 2: Use Build Arguments for Proxy

Run the build with proxy arguments:

```bash
docker compose build \
  --build-arg HTTP_PROXY=http://wired.meraki.com:8090 \
  --build-arg HTTPS_PROXY=http://wired.meraki.com:8090 \
  --build-arg NO_PROXY=localhost,127.0.0.1
```

## Option 3: Modify Dockerfiles to Handle Proxy

Add proxy configuration directly in the Dockerfile before apt-get commands.

## Option 4: Use Alternative Base Images

Switch to Alpine-based images which use different package repositories that might not be blocked.

## Option 5: Build Outside Corporate Network

If possible, build the images on a network without proxy restrictions, then save and load them:

```bash
# On unrestricted network:
docker compose build
docker save rag-101-api:latest rag-101-worker:latest -o rag-images.tar

# On restricted network:
docker load -i rag-images.tar
```