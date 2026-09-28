from math import cos, sin


def rectangle(center, width, height, angle=0.0):
    c, s = cos(angle), sin(angle)
    return tuple((center[0] + x*c - y*s, center[1] + x*s + y*c)
                 for x, y in ((-width/2, -height/2), (width/2, -height/2),
                              (width/2, height/2), (-width/2, height/2)))


def cross(a, b, p):
    return (b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0])


def contains(polygon, point):
    return all(cross(a, b, point) >= -1e-8 for a, b in zip(polygon, polygon[1:]+polygon[:1]))


def area(polygon):
    if len(polygon) < 3:
        return 0.0
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(polygon, polygon[1:]+polygon[:1]))) / 2


def intersection(subject, clip):
    """Sutherland-Hodgman clipping for consistently ordered convex polygons."""
    output = list(subject)
    for a, b in zip(clip, clip[1:]+clip[:1]):
        source, output = output, []
        if not source:
            break
        previous = source[-1]
        for current in source:
            dp, dc = cross(a, b, previous), cross(a, b, current)
            if (dc >= 0) != (dp >= 0):
                t = dp / (dp-dc)
                output.append((previous[0]+t*(current[0]-previous[0]),
                               previous[1]+t*(current[1]-previous[1])))
            if dc >= 0:
                output.append(current)
            previous = current
    return tuple(output)


def overlap(detection, roi):
    poly = rectangle(detection.center_xy, detection.width, detection.height, detection.angle_rad)
    return area(intersection(poly, roi)) / (detection.width*detection.height)
