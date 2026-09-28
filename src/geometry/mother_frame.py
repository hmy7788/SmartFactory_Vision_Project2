from math import cos, sin, pi, degrees


def major_axis(detection):
    angle = detection.angle_rad
    width, height = detection.width, detection.height
    if height > width:
        width, height = height, width
        angle += pi/2
    # Undirected OBB axis -> screen-right axis, not a physical H1 identity.
    angle = (angle + pi/2) % pi - pi/2
    return width, height, angle


def mother_pose(detection, config):
    width, height, angle = major_axis(detection)
    if abs(degrees(angle)) > config["max_mother_angle_deg"]:
        raise ValueError("MOTHER_ANGLE_OUT_OF_RANGE")
    return {"center": detection.center_xy, "width": width, "height": height,
            "angle_rad": angle, "u": (cos(angle), sin(angle)), "v": (-sin(angle), cos(angle))}
