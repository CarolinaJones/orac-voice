#!/bin/bash

# 1. Locate backup ZIP files in orac-voice/llm_archive
echo "=== Available Model Backups (.zip) ==="
backups=()

while IFS= read -r file; do
    if [ -f "$file" ]; then
        backups+=("$file")
    fi
done < <(find "$HOME/orac-voice/llm_archive" -maxdepth 1 -type f \( -name "*_backup.zip" -o -name "*_backup_v*.zip" \))

if [ ${#backups[@]} -eq 0 ]; then
    echo "No valid model backup .zip files found on in orac-voice/llm_archive. Exiting."
    exit 1
fi

for i in "${!backups[@]}"; do
    echo "[$((i+1))] $(basename "${backups[$i]}")"
done

# 2. Get user backup choice
echo ""
read -p "Select a archive number to restore (1-${#backups[@]}): " selection

if ! [[ "$selection" =~ ^[0-9]+$ ]] || [ "$selection" -lt 1 ] || [ "$selection" -gt "${#backups[@]}" ]; then
    echo "Invalid selection. Exiting."
    exit 1
fi

chosen_zip="${backups[$((selection-1))]}"
zip_filename=$(basename "$chosen_zip")
folder_name="${zip_filename%.zip}"

# 3. Create a clean workspace and unzip
tmp_dir=$(mktemp -d -t ollama_restore_XXXXXX)
echo "Extracting archive to secure temporary workspace..."
unzip -q "$chosen_zip" -d "$tmp_dir"

# Target paths inside extracted files
extracted_base="$tmp_dir/$folder_name"

if [ ! -d "$extracted_base/blobs" ] || [ ! -d "$extracted_base/manifests" ]; then
    echo "Error: Extracted archive does not contain a valid Ollama backup structure. Cleaning up."
    rm -rf "$tmp_dir"
    exit 1
fi

# 4. Cleanly parse the original model name and tag
raw_name=$(echo "$folder_name" | sed -E 's/_(backup)(_v[0-9]+)?$//')
model_part="${raw_name%_*}"
tag_part="${raw_name##*_}"
model_path_safe=$(echo "$model_part" | sed 's/_/\//g')

# 5. Set system target paths
ollama_blob_dir="$HOME/.ollama/models/blobs"
ollama_manifest_parent="$HOME/.ollama/models/manifests/registry.ollama.ai/library/$model_path_safe"
ollama_manifest_file="$ollama_manifest_parent/$tag_part"

# Ensure directories exist
mkdir -p "$ollama_blob_dir"
mkdir -p "$ollama_manifest_parent"

# 6. Prompt user before overwriting
if [ -f "$ollama_manifest_file" ]; then
    echo ""
    echo "Warning: Model tag '${model_part}:${tag_part}' already exists in your active system."
    read -p "Do you want to overwrite it? (y/n): " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "Restore cancelled. Cleaning workspace."
        rm -rf "$tmp_dir"
        exit 0
    fi
fi

# 7. Restore binary blobs
echo ""
echo "Restoring model dependency blobs to system registry..."
for blob_path in "$extracted_base/blobs"/*; do
    if [ -f "$blob_path" ]; then
        blob_name=$(basename "$blob_path")
        if [ ! -f "$ollama_blob_dir/$blob_name" ]; then
            cp "$blob_path" "$ollama_blob_dir/"
            echo "  -> Restored blob: $blob_name"
        else
            echo "  -> Blob already exists, skipping write: $blob_name"
        fi
    fi
done

# 8. Restore the manifest file under its exact required name
echo "Registering model structure manifest layout..."
backup_manifest_source=$(find "$extracted_base/manifests" -type f | head -n 1)
cp "$backup_manifest_source" "$ollama_manifest_file"

# 9. Clean up temporary directory layout
rm -rf "$tmp_dir"

echo ""
echo "Success! The model has been injected back into Ollama system frameworks."
echo "Verify it by running: 'ollama list'"
