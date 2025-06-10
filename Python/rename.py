import os

def rename_yolo_dataset_files(folder_path):
    """
    Renames files in a YOLO dataset folder by adding the base folder name as a suffix.
    For example: '1.jpg' -> '1-kiri-bawah.jpg' and '1.txt' -> '1-kiri-bawah.txt'
    
    Args:
        folder_path (str): Path to the folder containing the dataset files
    """
    # Check if folder exists
    if not os.path.isdir(folder_path):
        print(f"Error: Folder '{folder_path}' does not exist.")
        return
    
    # Extract the base folder name to use as suffix
    base_folder_name = os.path.basename(os.path.dirname(folder_path))
    
    # Get all files in the folder
    files = os.listdir(folder_path)
    
    # Process each file
    for file in files:
        # Get file extension
        file_path = os.path.join(folder_path, file)
        if os.path.isfile(file_path):
            file_name, file_ext = os.path.splitext(file)
            
            # Only process .jpg and .txt files
            if file_ext.lower() in ['.jpg', '.jpeg', '.txt']:
                # Create new filename with folder name as suffix
                new_name = f"{file_name}-{base_folder_name}{file_ext}"
                new_path = os.path.join(folder_path, new_name)
                
                # Rename the file
                try:
                    os.rename(file_path, new_path)
                    print(f"Renamed: {file} -> {new_name}")
                except Exception as e:
                    print(f"Error renaming {file}: {e}")

if __name__ == "__main__":
    folder_path = "kiri-bawah\\labels"
    rename_yolo_dataset_files(folder_path)
    print("Renaming complete!")
