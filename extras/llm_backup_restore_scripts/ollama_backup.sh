#!/bin/bash

# 1. Fetch and display installed models
echo "=== Available Ollama Models ==="
models=()
while IFS= read -r line; do
    if [[ ! "$line" =~ NAME ]]; then
        model_name=$(echo "$line" | awk '{print $1}')
        if [ -n "$model_name" ]; then
            models+=("$model_name")
        fi
    fi
done < <(ollama list)

if [ ${#models[@]} -eq 0 ]; then
    echo "No models found in Ollama. Exiting."
    exit 1
fi

for i in "${!models[@]}"; do
    echo "[$((i+1))] ${models[$i]}"
done

# 2. Get user model selection
echo ""
read -p "Select a model number to backup (1-${#models[@]}): " selection

if ! [[ "$selection" =~ ^[0-9]+$ ]] || [ "$selection" -lt 1 ] || [ "$selection" -gt "${#models[@]}" ]; then
    echo "Invalid selection. Exiting."
    exit 1
fi

chosen_model="${models[$((selection-1))]}"
echo "Selected: $chosen_model"

safe_name=$(echo "$chosen_model" | sed 's/:/_/g')
base_backup_dir="$HOME/orac-voice/llm_archive/${safe_name}_backup"
backup_dir="$base_backup_dir"

# 3. Handle pre-existing backup ZIP/Directory logic
if [ -d "$backup_dir" ] || [ -f "${backup_dir}.zip" ]; then
    echo ""
    echo "Warning: A backup for this model already exists in orac-voice/llm_archive."
    echo " [1] Overwrite existing backup"
    echo " [2] Create a new versioned file"
    echo " [3] Cancel operation"
    read -p "Choose an option (1-3): " folder_choice

    case "$folder_choice" in
        1)
            echo "Removing old backup files..."
            rm -rf "$backup_dir" "${backup_dir}.zip"
            ;;
        2)
            counter=1
            while [ -d "${base_backup_dir}_v${counter}" ] || [ -f "${base_backup_dir}_v${counter}.zip" ]; do
                ((counter++))
            done
            backup_dir="${base_backup_dir}_v${counter}"
            echo "Creating versioned layout: $(basename "$backup_dir")"
            ;;
        *)
            echo "Backup cancelled."
            exit 0
            ;;
    esac
fi

# 4. Resolve manifest path
if [[ "$chosen_model" == *"/"* ]]; then
    manifest_rel_path=$(echo "$chosen_model" | sed 's/:/\//')
else
    manifest_rel_path="library/$(echo "$chosen_model" | sed 's/:/\//')"
fi

manifest_source="$HOME/.ollama/models/manifests/registry.ollama.ai/$manifest_rel_path"

if [ ! -f "$manifest_source" ]; then
    echo "Error: Could not locate manifest file at $manifest_source"
    exit 1
fi

# 5. Copy operations
mkdir -p "$backup_dir/blobs"
mkdir -p "$backup_dir/manifests"
cp "$manifest_source" "$backup_dir/manifests/"

echo "Parsing manifest and copying unique dependency blobs..."
grep -o 'sha256:[a-f0-9]*' "$manifest_source" | sed 's/:/-/' | sort -u | while read -r blob; do
    if [ -f "$HOME/.ollama/models/blobs/$blob" ]; then
        cp "$HOME/.ollama/models/blobs/$blob" "$backup_dir/blobs/"
        echo "  -> Copied blob: $blob"
    else
        echo "  -> Warning: Expected blob $blob missing from system directory!"
    fi
done

# 6. New Step: Zip the directory and clean up
echo ""
echo "Compressing backup directory into a ZIP archive..."
cd "$HOME/orac-voice/llm_archive" || exit
zip -r "$(basename "$backup_dir").zip" "$(basename "$backup_dir")" > /dev/null

if [ $? -eq 0 ]; then
    rm -rf "$backup_dir"
    echo "Success! Model backed up to: ${backup_dir}.zip"
else
    echo "Error: Compression failed. Keeping raw folder layout at: $backup_dir"
fi
