# CI/CD Deployment Setup Guide

This guide will help you set up automatic deployment to your Oracle server on every push to the main branch.

## Step 1: Set up Git on Oracle Server

SSH into your Oracle server and run:

```bash
# Navigate to home directory
cd ~

# Clone the repository (if not already done)
git clone https://github.com/kashyap-hindocha/trading-bot-project.git trading-bot

# Or if directory exists, initialize git
cd trading-bot
git init
git remote add origin https://github.com/kashyap-hindocha/trading-bot-project.git
git fetch origin
git reset --hard origin/main
git branch --set-upstream-to=origin/main main
```

## Step 2: Generate SSH Key on Your Local Machine (for GitHub Actions)

On your **local machine**, generate a dedicated SSH key for deployments:

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/oracle_deploy_key -N ""
```

This creates:
- Private key: `~/.ssh/oracle_deploy_key`
- Public key: `~/.ssh/oracle_deploy_key.pub`

## Step 3: Add Public Key to Oracle Server

Copy the public key to your Oracle server:

```bash
# Display the public key
cat ~/.ssh/oracle_deploy_key.pub

# Copy it, then SSH to your Oracle server and add it:
ssh your-server
echo "YOUR_PUBLIC_KEY_HERE" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Test the connection:
```bash
ssh -i ~/.ssh/oracle_deploy_key your-user@your-server-ip
```

## Step 4: Add Secrets to GitHub Repository

Go to your GitHub repository:
1. Navigate to **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add the following secrets:

| Secret Name | Value | Description |
|------------|-------|-------------|
| `SERVER_HOST` | Your Oracle server IP | e.g., `123.45.67.89` |
| `SERVER_USER` | Your server username | e.g., `ubuntu` or `opc` |
| `SERVER_SSH_KEY` | Private key content | Content of `~/.ssh/oracle_deploy_key` |
| `SERVER_PORT` | SSH port (optional) | Default is 22 |

To get the private key content:
```bash
cat ~/.ssh/oracle_deploy_key
```

Copy the **entire output** including the `-----BEGIN` and `-----END` lines.

## Step 5: Make Deployment Script Executable (on Server)

SSH to your Oracle server:

```bash
cd ~/trading-bot
chmod +x deploy.sh
```

## Step 6: Test the Setup

1. Make a small change to your local repository
2. Commit and push:
   ```bash
   git add .
   git commit -m "Test CI/CD deployment"
   git push origin main
   ```

3. Go to GitHub → **Actions** tab to watch the deployment

4. Check the deployment on your server:
   ```bash
   ssh your-server
   cd ~/trading-bot
   git log -1  # Should show your latest commit
   ```

## Workflow Features

The GitHub Actions workflow will:
- ✅ Trigger on every push to `main` branch
- ✅ Connect to your Oracle server via SSH
- ✅ Pull the latest changes
- ✅ Install dependencies if `requirements.txt` changed
- ✅ Restart bot and server services if they're running
- ✅ Log deployment status

## Troubleshooting

### Connection refused
- Check firewall rules on Oracle server
- Verify SSH port (default 22)
- Ensure public key is in `~/.ssh/authorized_keys`

### Permission denied
- Check private key is correctly added to GitHub secrets
- Verify SSH key permissions on server: `chmod 600 ~/.ssh/authorized_keys`

### Services not restarting
- Ensure systemd services are set up as user services
- Check service status: `systemctl --user status bot.service`
- Check logs: `journalctl --user -u bot.service -f`

### Manual deployment
If needed, you can manually run the deployment script on the server:
```bash
cd ~/trading-bot
./deploy.sh
```

## Optional: Deploy to Specific Branch

To deploy from different branches, modify `.github/workflows/deploy.yml`:

```yaml
on:
  push:
    branches:
      - main
      - production
      - staging
```

## Security Notes

- Keep your SSH private key secure
- Never commit SSH keys to the repository
- Use GitHub Secrets for sensitive data
- Regularly rotate deployment keys
- Limit SSH key access to specific commands if needed
