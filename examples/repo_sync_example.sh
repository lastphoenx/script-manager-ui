#!/bin/bash
# Sync-Skript für alle Repositories
# Füge script-manager-ui hinzu

set -e

REPOS=(
    "/opt/pcloud-tools:https://github.com/lastphoenx/pcloud-tools.git:main"
    "/opt/entropywatcher:https://github.com/lastphoenx/entropy-watcher-und-clamav-scanner.git:main"
    "/opt/rtb:https://github.com/lastphoenx/rtb.git:main"
    "/opt/apps/script-manager-ui:https://github.com/DEIN_USERNAME/script-manager-ui.git:main"
)

for entry in "${REPOS[@]}"; do
    IFS=':' read -r path url branch <<< "$entry"
    
    echo "=========================================="
    echo "Syncing: $path"
    echo "=========================================="
    
    if [ -d "$path/.git" ]; then
        cd "$path"
        
        # Stash local changes
        if ! git diff-index --quiet HEAD --; then
            echo "Local changes detected, stashing..."
            git stash
        fi
        
        # Pull
        git pull origin "$branch"
        
        echo "✓ $path synced"
    else
        echo "⚠️  $path is not a git repository, skipping"
    fi
    
    echo ""
done

echo "All repositories synced!"

# Restart services if needed
if systemctl is-active --quiet script-manager-ui; then
    echo "Restarting script-manager-ui..."
    sudo systemctl restart script-manager-ui
fi
