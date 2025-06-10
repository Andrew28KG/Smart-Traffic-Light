import os
import random
import shutil

# Define paths
dataset_root = 'dataset_1'
images_dir = os.path.join(dataset_root, 'images')
labels_dir = os.path.join(dataset_root, 'labels')
classes_file = os.path.join(dataset_root, 'classes.txt')

# Create output directories
output_root = 'yolo_dataset'
os.makedirs(output_root, exist_ok=True)

for split in ['train', 'val', 'test']:
    # Create directories for images and labels
    os.makedirs(os.path.join(output_root, split, 'images'), exist_ok=True)
    os.makedirs(os.path.join(output_root, split, 'labels'), exist_ok=True)

# Get list of all files (use image files as reference)
image_files = [f for f in os.listdir(images_dir) if f.lower().endswith(('.bmp', '.png', '.jpg', '.jpeg'))]
random.shuffle(image_files)  # Shuffle to ensure random distribution

# Split according to 70/20/10 ratio
total_files = len(image_files)
train_count = int(total_files * 0.7)
val_count = int(total_files * 0.2)

train_files = image_files[:train_count]
val_files = image_files[train_count:train_count + val_count]
test_files = image_files[train_count + val_count:]

# Function to copy files for a given split
def copy_files(file_list, split):
    for img_file in file_list:
        # Image file
        src_img = os.path.join(images_dir, img_file)
        dst_img = os.path.join(output_root, split, 'images', img_file)
        shutil.copy2(src_img, dst_img)
        
        # Label file
        label_file = os.path.splitext(img_file)[0] + '.txt'
        src_label = os.path.join(labels_dir, label_file)
        dst_label = os.path.join(output_root, split, 'labels', label_file)
        if os.path.exists(src_label):
            shutil.copy2(src_label, dst_label)

# Copy files to respective directories
copy_files(train_files, 'train')
copy_files(val_files, 'val')
copy_files(test_files, 'test')

# Create data.yaml file
with open(classes_file, 'r') as f:
    classes = [line.strip() for line in f if line.strip()]

yaml_content = f"""
path: {os.path.abspath(output_root)}
train: train/images
val: val/images
test: test/images

nc: {len(classes)}
names: {classes}
"""

with open(os.path.join(output_root, 'data.yaml'), 'w') as f:
    f.write(yaml_content.strip())

# Print statistics
print(f"Dataset split complete!")
print(f"Total files: {total_files}")
print(f"Train: {len(train_files)} files ({len(train_files)/total_files*100:.1f}%)")
print(f"Validation: {len(val_files)} files ({len(val_files)/total_files*100:.1f}%)")
print(f"Test: {len(test_files)} files ({len(test_files)/total_files*100:.1f}%)")
print(f"\nData.yaml created at: {os.path.join(output_root, 'data.yaml')}") 