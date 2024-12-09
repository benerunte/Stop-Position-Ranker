import numpy as np
from scipy.ndimage import measurements
import cv2
import os
import numpy as np
import PIL.Image as pil
from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
import matplotlib as mpl
from matplotlib import pyplot as plt
import matplotlib.cm as cm


def overlay(image, mask, color, alpha, resize=None):
    """Combines image and its segmentation mask into a single image.
    https://www.kaggle.com/code/purplejester/showing-samples-with-segmentation-mask-overlay

    Params:
        image: Training image. np.ndarray,
        mask: Segmentation mask. np.ndarray,
        color: Color for segmentation mask rendering.  tuple[int, int, int] = (255, 0, 0)
        alpha: Segmentation mask's transparency. float = 0.5,
        resize: If provided, both image and its mask are resized before blending them together.
        tuple[int, int] = (1024, 1024))

    Returns:
        image_combined: The combined image. np.ndarray

    """
    color = color[::-1]
    colored_mask = np.expand_dims(mask, 0).repeat(3, axis=0)
    colored_mask = np.moveaxis(colored_mask, 0, -1)
    masked = np.ma.MaskedArray(image, mask=colored_mask, fill_value=color)
    image_overlay = masked.filled()

    if resize is not None:
        image = cv2.resize(image.transpose(1, 2, 0), resize)
        image_overlay = cv2.resize(image_overlay.transpose(1, 2, 0), resize)

    image_combined = cv2.addWeighted(image, 1 - alpha, image_overlay, alpha, 0)

    return image_combined

def visualize_depth(disp_resized_np):
    print(np.size(disp_resized_np))
    vmax = np.percentile(disp_resized_np, 95)

    normalizer = mpl.colors.Normalize(vmin=disp_resized_np.min(), vmax=vmax)
    mapper = cm.ScalarMappable(norm=normalizer, cmap='plasma_r')
    # mapper = cm.ScalarMappable(norm=normalizer, cmap='viridis')
    colormapped_im = (mapper.to_rgba(disp_resized_np)[:, :, :3] * 255).astype(np.uint8)
    im = pil.fromarray(colormapped_im)

    name_dest_im = "visualize_depth.jpeg"
    # plt.imsave(name_dest_im, disp_resized_np, cmap='gray') # for saving as gray depth maps
    im.save(name_dest_im) # for saving as colored depth maps

def rotate_point(param, start_point, angle):
    x, y = param
    x0, y0 = start_point
    x_rot = x0 + np.cos(angle) * (x - x0) - np.sin(angle) * (y - y0)
    y_rot = y0 + np.sin(angle) * (x - x0) + np.cos(angle) * (y - y0)
    return int(x_rot), int(y_rot)

def clamp_point(point, width, height):
    x, y = point
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    return int(x), int(y)

def check_remaining_space(edge_start, edge_end, box_corners, car_length_depth):
    """
    Check remaining space on an edge after placing a box

    Parameters:
    edge_start: tuple of (x,y) for edge start
    edge_end: tuple of (x,y) for edge end
    box_corners: list of (x,y) tuples representing the placed box corners
    car_length_depth: minimum length needed for a new car
    """
    # Calculate total edge length
    edge_length = np.sqrt((edge_end[0] - edge_start[0]) ** 2 + (edge_end[1] - edge_start[1]) ** 2)

    # Find box extent along edge direction
    edge_vector = np.array([edge_end[0] - edge_start[0], edge_end[1] - edge_start[1]])
    edge_unit = edge_vector / np.linalg.norm(edge_vector)

    # Project box corners onto edge direction
    projections = []
    for corner in box_corners:
        corner_vector = np.array([corner[0] - edge_start[0], corner[1] - edge_start[1]])
        proj = np.dot(corner_vector, edge_unit)
        projections.append(proj)

    box_min = min(projections)
    box_max = max(projections)

    # Calculate remaining spaces
    space_before = box_min
    space_after = edge_length - box_max

    # Return True if either space is large enough for another car
    return space_before > car_length_depth or space_after > car_length_depth

def boxes_overlap(box1, box2, min_distance=1):
    """
    Check if two boxes overlap or are too close.

    Parameters:
        box1, box2 (list of tuples): Corners of the boxes [(x1, y1), (x2, y2), ...].
        min_distance (int): Minimum distance between any two corners of the boxes.

    Returns:
        bool: True if boxes overlap or are too close, False otherwise.
    """
    def separating_axis_theorem(box1, box2):
        for box in [box1, box2]:
            for i in range(len(box)):
                # Calculate edge vector
                edge = np.array(box[(i + 1) % len(box)]) - np.array(box[i])
                axis = np.array([-edge[1], edge[0]])  # Perpendicular vector
                # Project all points of both boxes onto the axis
                proj1 = [np.dot(np.array(corner), axis) for corner in box1]
                proj2 = [np.dot(np.array(corner), axis) for corner in box2]
                # Check for overlap in projections
                if max(proj1) <= min(proj2) or max(proj2) <= min(proj1):
                    return False  # Found a separating axis or just touching
        return True  # No separating axis found, boxes overlap

    # Check for overlapping interiors
    if separating_axis_theorem(box1, box2):
        return True

    # Check for proximity between corners
    # for corner1 in box1:
    #     for corner2 in box2:
    #         distance = np.linalg.norm(np.array(corner1) - np.array(corner2))
    #         if distance < min_distance:
    #             return True

    return False

def scale_depth(depth_value, depth_min, depth_max, epsilon=1e-6):
    # Function to scale depth values

    depth_value = np.clip(depth_value, depth_min + epsilon, depth_max - epsilon)
    return (depth_max - depth_value) / ((depth_max - depth_min) + epsilon)

def main():
    clip = 7
    frame = 8
    image_mask = np.load(f'/home/anirudh/work_dir/Stop-Position-Ranker/Data/processed/clip_{clip}/{frame}.npy')
    img = cv2.imread(f'/home/anirudh/work_dir/Stop-Position-Ranker/Data/dataset/annotation_image_action_without_bb/clip_{clip}/{frame}_without_bb.png')
    path_to_depth = f"/home/anirudh/work_dir/Stop-Position-Ranker/Data/processed_depth/clip_{clip}/{frame}_without_bb_disp.npy"
    disp_resized_np = np.load(path_to_depth).squeeze()

    previous_boxes = []
    # select pixels with label class as road
    road_only = np.where(image_mask == 0, 1, 0)

    #finding 3 biggest clusters of pixels
    lw, num = measurements.label(road_only)
    unique, counts = np.unique(lw, return_counts=True)
    ind = np.argpartition(-counts, kth=4)[:4]
    road_after_filter = np.zeros(np.shape(lw))
    for cluster_id in unique[ind]:
        if cluster_id != 0:
            road_after_filter = np.where(lw == cluster_id, 1, 0)
    ## visualize the depth if necessary
    # visualize_depth(disp_resized_np)

    STEREO_SCALE_FACTOR = 1

    #lw = analyze_space(road_mask=road_after_filter, depth_map=path_to_depth)

    # read the npy file and print the values
    # Extract depth values only for road pixels
    road_depth_mask = (road_after_filter > 0)  # Assuming road pixels are marked as 1
    road_depth_values = disp_resized_np[road_depth_mask]

    # print(f"Depth values: {depth_values}")
    # print(f"min value: {np.min(depth_values)}")
    # print(f"road min value: {np.min(road_depth_values)}")
    # print(f"max value: {np.max(depth_values)}")
    # print(f"road max value: {np.max(road_depth_values)}")
    # print(f"mean value: {np.mean(depth_values)}")
    # print(f"road mean value: {np.mean(road_depth_values)}")

    road_and_edge = np.where(image_mask == 0, 1, 0)

    image_with_masks = np.copy(img)
    road_pixels = np.where(image_mask == 0)  # Find coordinates where value is 0 (assuming 0 represents 'road')
    border_points = np.where(image_mask == 1)  # Assuming 1 represents 'border_points'



    for x, y in zip(*road_pixels):
        image_with_masks = cv2.circle(image_with_masks, (y, x), 1, (0, 255, 0), -1)

    for x, y in zip(*border_points):
        image_with_masks = cv2.circle(image_with_masks, (y, x), 1, (255, 0, 0), -1)
    #make a copy of the image
    #image = np.copy(img)

    # Assuming `image_mask` is loaded, where 1 represents border points
    border_points_mask = np.where(image_mask == 1, 255, 0).astype(np.uint8)

    # Apply edge detection using Canny
    edges = cv2.Canny(border_points_mask, threshold1=100, threshold2=200)

    # Find contours (edge points)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)


    contours = list(contours)

    # Create a blank image for the lines
    line_image = np.zeros_like(img)


    height, width = disp_resized_np.shape  # Get array dimensions

    # Clamp function to ensure points stay within bounds


    for contour in contours:
        if len(contour) < 10:  # Skip very small contours
            continue
        # Fit a straight line to the entire contour
        [vx, vy, x, y] = cv2.fitLine(contour, cv2.DIST_L2, 0, 0.01, 0.01)

        # Project contour points onto the line
        projections = []
        for point in contour:
            px, py = point[0]
            # Parametric projection of the point onto the line
            t = vx * (px - x) + vy * (py - y)
            projections.append([x + t * vx, y + t * vy])
        projections = np.array(projections)

        # Find the extreme points along the line
        min_t_idx = np.argmin(projections[:, 0] * vx + projections[:, 1] * vy)
        max_t_idx = np.argmax(projections[:, 0] * vx + projections[:, 1] * vy)

        # Convert to integer and clamp within bounds
        start_point = clamp_point(projections[min_t_idx], width, height)
        end_point = clamp_point(projections[max_t_idx], width, height)

        # Access depth values at valid indices
        start_depth = disp_resized_np[start_point[1], start_point[0]]
        end_depth = disp_resized_np[end_point[1], end_point[0]]

        print(f"Start Point: {start_point}, End Point: {end_point}")
        print(f"Start Depth: {start_depth}, End Depth: {end_depth}")

        # Compute the 3D distance
        length_3d = np.sqrt(
            (start_point[0] - end_point[0])**2 +
            (start_point[1] - end_point[1])**2 +
            (start_depth - end_depth)**2
        )


        # Draw the line
        if length_3d > 350:
            print(f"3D length of edge: {length_3d}")
            cv2.line(line_image, start_point, end_point, (0, 255, 0), 2)

            angle = np.arctan2(vy, vx)  # Angle in radians
            print(f"Angle: {angle}")



            # Car size without depth
            car_length = 450
            car_width = 240
            # Draw the car along the line and rotate it to match the line orientation
            #cv2.rectangle(line_image, start_point, end_point, (0, 0, 255), 2)
            # Extract depth values for the start and end points
            # start_depth = disp_resized_np[start_point[1], start_point[0]] * STEREO_SCALE_FACTOR
            # end_depth = disp_resized_np[end_point[1], end_point[0]] * STEREO_SCALE_FACTOR

            # Normalize the depth values
            #depth_min = np.min(disp_resized_np)
            #depth_max = np.max(disp_resized_np)
            depth_min_road = np.min(road_depth_values)
            depth_max_road = np.max(road_depth_values)
            # Use percentiles to exclude outliers
            #depth_min_road = np.percentile(road_depth_values, 1)  # Bottom 5%
            #depth_max_road = np.percentile(road_depth_values, 99)  # Top 95%
            #print(f"Depth Min: {depth_min}, Depth Max: {depth_max}")

            #start_depth_normalized = (start_depth - depth_min_road) / (depth_max_road - depth_min_road)
            #end_depth_normalized = (end_depth - depth_min_road) / (depth_max_road - depth_min_road)
            #start_depth_normalized = np.log1p(start_depth - depth_min_road) / np.log1p(depth_max_road - depth_min_road)
            #end_depth_normalized = np.log1p(end_depth - depth_min_road) / np.log1p(depth_max_road - depth_min_road)
            start_depth_normalized = np.log1p(max(start_depth - depth_min_road, 0)) / np.log1p(depth_max_road - depth_min_road)
            end_depth_normalized = np.log1p(max(end_depth - depth_min_road, 0)) / np.log1p(depth_max_road - depth_min_road)

            print(f"Road Depth Min: {depth_min_road}")
            print(f"Road Depth Max: {depth_max_road}")
            print(f"Start Depth: {start_depth}")
            print(f"End Depth: {end_depth}")


            

            # Scale all depth values in the road_depth_values array
            scaled_depths = np.array([
                scale_depth(value, depth_min_road, depth_max_road)
                for value in road_depth_values
            ])

            # Scale start and end depths
            start_depth_scaled = scale_depth(start_depth, depth_min_road, depth_max_road)
            end_depth_scaled = scale_depth(end_depth, depth_min_road, depth_max_road)



            print(f"Scaled Start Depth: {float(start_depth_scaled)}")
            print(f"Scaled End Depth: {float(end_depth_scaled)}")


            #start_depth_normalized = np.clip(start_depth_normalized, 0, 1)
            #end_depth_normalized = np.clip(end_depth_normalized, 0, 1)
            #mean_depth_normalized = (start_depth_normalized + end_depth_normalized) / 2
            mean_depth_normalized = (start_depth_scaled + end_depth_scaled) / 2


            #start_depth_normalized = (start_depth - disp_resized_np.min()) / (disp_resized_np.max() - disp_resized_np.min())
            #end_depth_normalized = (end_depth - disp_resized_np.min()) / (disp_resized_np.max() - disp_resized_np.min())

            print(f"start_depth_normalized: {start_depth_normalized}")
            print(f"end_depth_normalized: {end_depth_normalized}")
            print(f"mean_depth_normalized: {mean_depth_normalized}")


            print(f"start_depth: {start_depth}")
            print(f"end_depth: {end_depth}")


            #Car size with depth
            #if start_depth_normalized > 1:
            # car_length_depth = 450/mean_depth_normalized
            # car_width_depth = 240/mean_depth_normalized

            # Adjust car dimensions
            #scaling_factor = 20
            #car_length_depth = int(450 * scaling_factor / mean_depth_normalized)
            #car_width_depth = int(240 * scaling_factor / mean_depth_normalized)
            car_length_depth = int(450 * mean_depth_normalized)
            car_width_depth = int(240 * mean_depth_normalized)

            # Update car dimensions
            car_length = int(car_length_depth)
            car_width = int(car_width_depth)

            corner_1 = (start_point[0], start_point[1])
            corner_2 = (start_point[0] + car_length, start_point[1])
            corner_3 = (start_point[0] + car_length, start_point[1] + car_width)
            corner_4 = (start_point[0], start_point[1] + car_width)
            corners = [corner_1, corner_2, corner_3, corner_4]
            corners = [rotate_point(corner, start_point, angle) for corner in corners]

            # Check against previous boxes
            overlap_found = False
            for i in range(0, len(previous_boxes), 4):  # Iterate over groups of 4 corners
                prev_corners = previous_boxes[i:i + 4]
                if boxes_overlap(corners, prev_corners):
                    overlap_found = True
                    break
            #print(f"§$§$§${len(previous_boxes)}")

            if not overlap_found:
                # Rotate and draw the box if no overlap
                for i in range(4):
                    cv2.line(line_image, corners[i], corners[(i + 1) % 4], (0, 0, 255), 2)

                    # # Check remaining space
                    # has_space = check_remaining_space(
                    #     start_point,
                    #     end_point,
                    #     corners,
                    #     car_length_depth
                    # )

                    # if has_space:
                    #     print(f"Enough space remains for another car on this edge")
                    #     # Process remaining contour
                    #     remaining_start = corners[2]
                    #     remaining_contour = np.array([
                    #         [remaining_start],
                    #         [end_point]
                    #     ], dtype=np.int32)
                    #     contours.append(remaining_contour)


                # Add the current box to the list of previous boxes
                previous_boxes.extend(corners)
            else:
                print("Overlap detected. Adjust position or size.")


            #
            # for i in range(4):
            #     corners[i] = rotate_point(corners[i], start_point, angle)
            # for i in range(4):
            #     cv2.line(line_image, corners[i], corners[(i + 1) % 4], (0, 0, 255), 2)

            # Draw the car along the line and rotate it to match the line orientation
            #cv2.rectangle(line_image, start_point, end_point, (0, 0, 255), 2)

    edges_colored = np.zeros((edges.shape[0], edges.shape[1], 3), dtype=np.uint8)

    # Set detected edges to red (BGR format: Blue=0, Green=0, Red=255)
    edges_colored[edges != 0] = (0, 0, 255)

    combined_image = cv2.addWeighted(edges_colored, 0.8, line_image, 0.8, 0)


    image_with_outlines_and_lines = cv2.addWeighted(img, 0.8, combined_image, 0.8, 0)

    # Save or display the resulting image
    output_path = f'edges_aligned_with_longest_straight_part_clip_{clip}_frame_{frame}.png'
    cv2.imwrite(output_path, image_with_outlines_and_lines)
    print(f"###NEW PICTURE {output_path}######")

if __name__ == "__main__": 
    main() 