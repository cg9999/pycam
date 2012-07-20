# -*- coding: utf-8 -*-
"""
$Id$

Copyright 2010 Lars Kruse <devel@sumpfralle.de>

This file is part of PyCAM.

PyCAM is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

PyCAM is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with PyCAM.  If not, see <http://www.gnu.org/licenses/>.
"""

from pycam.Geometry.PointUtils import *
from pycam.Geometry.Line import Line
from pycam.Geometry.utils import epsilon
from pycam.Geometry.Polygon import PolygonSorter
import pycam.Utils.log
import pycam.Geometry

import math


_log = pycam.Utils.log.get_logger()


GRID_DIRECTION_X = 0
GRID_DIRECTION_Y = 1
GRID_DIRECTION_XY = 2

MILLING_STYLE_IGNORE = 0
MILLING_STYLE_CONVENTIONAL = 1
MILLING_STYLE_CLIMB = 2

START_X = 0x1
START_Y = 0x2
START_Z = 0x4

SPIRAL_DIRECTION_IN = 0
SPIRAL_DIRECTION_OUT = 1

POCKETING_TYPE_NONE = 0
POCKETING_TYPE_HOLES = 1
POCKETING_TYPE_MATERIAL = 2


def isiterable(obj):
    try:
        iter(obj)
        return True
    except TypeError:
        return False

def floatrange(start, end, inc=None, steps=None, reverse=False):
    if reverse:
        start, end = end, start
        # 'inc' will be adjusted below anyway
    if abs(start - end) < epsilon:
        yield start
    elif inc is None and steps is None:
        raise ValueError("floatrange: either 'inc' or 'steps' must be provided")
    elif (not steps is None) and (steps < 2):
        raise ValueError("floatrange: 'steps' must be greater than 1")
    else:
        # the input is fine
        # reverse increment, if it does not suit start/end
        if steps is None:
            if ((end - start) > 0) != (inc > 0):
                inc = -inc
            steps = int(math.ceil(float(end - start) / inc) + 1)
        inc = float(end - start) / (steps - 1)
        for index in range(steps):
            yield start + inc * index

def get_fixed_grid_line(start, end, line_pos, z, step_width=None,
        grid_direction=GRID_DIRECTION_X):
    if step_width is None:
        # useful for PushCutter operations
        steps = (start, end)
    elif isiterable(step_width):
        steps = step_width
    else:
        steps = floatrange(start, end, inc=step_width)
    if grid_direction == GRID_DIRECTION_X:
        get_point = lambda pos: (pos, line_pos, z)
    else:
        get_point = lambda pos: (line_pos, pos, z)
    for pos in steps:
        yield get_point(pos)

def get_fixed_grid_layer(minx, maxx, miny, maxy, z, line_distance,
        step_width=None, grid_direction=GRID_DIRECTION_X,
        milling_style=MILLING_STYLE_IGNORE, start_position=0):
    if grid_direction == GRID_DIRECTION_XY:
        raise ValueError("'get_one_layer_fixed_grid' does not accept XY " \
                + "direction")
    # zigzag is only available if the milling 
    zigzag = (milling_style == MILLING_STYLE_IGNORE)
    # If we happen to start at a position that collides with the milling style,
    # then we need to move to the closest other corner. Here we decide, which
    # would be the best alternative.
    def get_alternative_start_position(start):
        if (maxx - minx) <= (maxy - miny):
            # toggle the X position bit
            return start ^ START_X
        else:
            # toggle the Y position bit
            return start ^ START_Y
    if grid_direction == GRID_DIRECTION_X:
        primary_dir = START_X
        secondary_dir = START_Y
    else:
        primary_dir = START_Y
        secondary_dir = START_X
    # Determine the starting direction (assuming we begin at the lower x/y
    # coordinates.
    if milling_style == MILLING_STYLE_IGNORE:
        # just move forward - milling style is not important
        pass
    elif (milling_style == MILLING_STYLE_CLIMB) == \
            (grid_direction == GRID_DIRECTION_X):
        if bool(start_position & START_X) == bool(start_position & START_Y):
            # we can't start from here - choose an alternative
            start_position = get_alternative_start_position(start_position)
    elif (milling_style == MILLING_STYLE_CONVENTIONAL) == \
            (grid_direction == GRID_DIRECTION_X):
        if bool(start_position & START_X) != bool(start_position & START_Y):
            # we can't start from here - choose an alternative
            start_position = get_alternative_start_position(start_position)
    else:
        raise ValueError("Invalid milling style given: %s" % str(milling_style))
    # sort out the coordinates (primary/secondary)
    if grid_direction == GRID_DIRECTION_X:
        start, end = minx, maxx
        line_start, line_end = miny, maxy
    else:
        start, end = miny, maxy
        line_start, line_end = minx, maxx
    # switch start/end if we move from high to low
    if start_position & primary_dir:
        start, end = end, start
    if start_position & secondary_dir:
        line_start, line_end = line_end, line_start
    # calculate the line positions
    if isiterable(line_distance):
        lines = line_distance
    else:
        lines = floatrange(line_start, line_end, inc=line_distance)
    # at the end of the layer we will be on the other side of the 2nd direction
    end_position = start_position ^ secondary_dir
    # the final position will probably be on the other side (primary)
    if not zigzag:
        end_position ^= primary_dir
    # calculate each line
    def get_lines(start, end, end_position):
        result = []
        for line_pos in lines:
            result.append(get_fixed_grid_line(start, end, line_pos, z,
                    step_width=step_width, grid_direction=grid_direction))
            if zigzag:
                start, end = end, start
                end_position ^= primary_dir
        return result, end_position
    return get_lines(start, end, end_position)

def get_fixed_grid((low, high), layer_distance, line_distance=None,
        step_width=None, grid_direction=GRID_DIRECTION_X,
        milling_style=MILLING_STYLE_IGNORE, start_position=START_Z):
    """ Calculate the grid positions for toolpath moves
    """
    if isiterable(layer_distance):
        layers = layer_distance
    elif layer_distance is None:
        # useful for DropCutter
        layers = [low[2]]
    else:
        layers = floatrange(low[2], high[2], inc=layer_distance,
                reverse=bool(start_position & START_Z))
    def get_layers_with_direction(layers):
        for layer in layers:
            # this will produce a nice xy-grid, as well as simple x and y grids
            if grid_direction != GRID_DIRECTION_Y:
                yield (layer, GRID_DIRECTION_X)
            if grid_direction != GRID_DIRECTION_X:
                yield (layer, GRID_DIRECTION_Y)
    for z, direction in get_layers_with_direction(layers):
        result, start_position = get_fixed_grid_layer(low[0], high[0],
                low[1], high[1], z, line_distance, step_width=step_width,
                grid_direction=direction, milling_style=milling_style,
                start_position=start_position)
        yield result

def _get_position(minx, maxx, miny, maxy, z, position):
    if position & START_X > 0:
        x = minx
    else:
        x = maxx
    if position & START_Y > 0:
        y = miny
    else:
        y = maxy
    return (x, y, z)

def get_spiral_layer_lines(minx, maxx, miny, maxy, z, line_distance_x,
        line_distance_y, grid_direction, start_position, current_location):
    xor_map = {GRID_DIRECTION_X: START_X, GRID_DIRECTION_Y: START_Y}
    end_position = start_position ^ xor_map[grid_direction]
    end_location = _get_position(minx, maxx, miny, maxy, z, end_position)
    lines = [(current_location, end_location)]
    if grid_direction == GRID_DIRECTION_X:
        next_grid_direction = GRID_DIRECTION_Y
        if start_position & START_Y > 0:
            miny += line_distance_y
        else:
            maxy -= line_distance_y
    else:
        next_grid_direction = GRID_DIRECTION_X
        if start_position & START_X > 0:
            minx += line_distance_x
        else:
            maxx -= line_distance_x
    if (minx - epsilon <= maxx ) and (miny - epsilon <= maxy):
        # recursively compute the next lines
        lines.extend(get_spiral_layer_lines(minx, maxx, miny, maxy, z,
                line_distance_x, line_distance_y, next_grid_direction,
                end_position, end_location))
    return lines

def get_spiral_layer(minx, maxx, miny, maxy, z, line_distance, step_width,
        grid_direction, start_position, rounded_corners, reverse):
    current_location = _get_position(minx, maxx, miny, maxy, z,
            start_position)
    if line_distance > 0:
        line_steps_x = math.ceil((float(maxx - minx) / line_distance))
        line_steps_y = math.ceil((float(maxy - miny) / line_distance))
        line_distance_x = (maxx - minx) / line_steps_x
        line_distance_y = (maxy - miny) / line_steps_y
        lines = get_spiral_layer_lines(minx, maxx, miny, maxy, z,
                line_distance_x, line_distance_y, grid_direction,
                start_position, current_location)
        if reverse:
            lines.reverse()
        # turn the lines into steps
        if rounded_corners:
            rounded_lines = []
            previous = None
            for index, (start, end) in enumerate(lines):
                radius = 0.5 * min(line_distance_x, line_distance_y)
                edge_vector = psub(end,start)
                # TODO: ellipse would be better than arc
                offset = pmul(pnormalized(edge_vector), radius)
                if previous:
                    start = padd(start, offset)
                    center = padd(previous, offset)
                    up_vector = pnormalized(pcross(psub(previous, center), psub(start, center)))
                    north = padd(center, (1.0, 0.0, 0.0, 'v'))
                    angle_start = pycam.Geometry.get_angle_pi(north, center, previous, up_vector, pi_factor=True) * 180.0
                    angle_end = pycam.Geometry.get_angle_pi(north, center, start, up_vector, pi_factor=True) * 180.0
                    # TODO: remove these exceptions based on up_vector.z (get_points_of_arc does not respect the plane, yet)
                    if up_vector[2] < 0:
                        angle_start, angle_end = -angle_end, -angle_start
                    arc_points = pycam.Geometry.get_points_of_arc(center, radius, angle_start, angle_end)
                    if up_vector[2] < 0:
                        arc_points.reverse()
                    for arc_index in range(len(arc_points) - 1):
                        p1_coord = arc_points[arc_index]
                        p2_coord = arc_points[arc_index + 1]
                        p1 = (p1_coord[0], p1_coord[1], z)
                        p2 = (p2_coord[0], p2_coord[1], z)
                        rounded_lines.append((p1, p2))
                if index != len(lines) - 1:
                    end = psub(end, offset)
                previous = end
                rounded_lines.append((start, end))
            lines = rounded_lines
        for start, end in lines:
            points = []
            if step_width is None:
                points.append(start)
                points.append(end)
            else:
                line = Line(start, end)
                if isiterable(step_width):
                    steps = step_width
                else:
                    steps = floatrange(0.0, line.len, inc=step_width)
                for step in steps:
                    next_point = padd(line.p1, pmul(line.dir, step))
                    points.append(next_point)
            if reverse:
                points.reverse()
            yield points

def get_spiral((low, high), layer_distance, line_distance=None,
        step_width=None, milling_style=MILLING_STYLE_IGNORE,
        spiral_direction=SPIRAL_DIRECTION_IN, rounded_corners=False,
        start_position=(START_X | START_Y | START_Z)):
    """ Calculate the grid positions for toolpath moves
    """
    if isiterable(layer_distance):
        layers = layer_distance
    elif layer_distance is None:
        # useful for DropCutter
        layers = [low[2]]
    else:
        layers = floatrange(low[2], high[2], inc=layer_distance,
                reverse=bool(start_position & START_Z))
    if (milling_style == MILLING_STYLE_CLIMB) == \
            (start_position & START_X > 0):
        start_direction = GRID_DIRECTION_X
    else:
        start_direction = GRID_DIRECTION_Y
    reverse = (spiral_direction == SPIRAL_DIRECTION_OUT)
    for z in layers:
        yield get_spiral_layer(low[0], high[0], low[1], high[1], z,
                line_distance, step_width=step_width,
                grid_direction=start_direction, start_position=start_position,
                rounded_corners=rounded_corners, reverse=reverse)

def get_lines_layer(lines, z, last_z=None, step_width=None,
        milling_style=MILLING_STYLE_CONVENTIONAL):
    get_proj_point = lambda proj_point: (proj_point[0], proj_point[1], z)
    projected_lines = []
    for line in lines:
        if (not last_z is None) and (last_z < line.minz):
            # the line was processed before
            continue
        elif line.minz < z < line.maxz:
            # Split the line at the point at z level and do the calculation
            # for both point pairs.
            factor = (z - line.p1[2]) / (line.p2[2] - line.p1[2])
            plane_point = padd(line.p1, pmul(line.vector, factor))
            if line.p1[2] < z:
                p1 = get_proj_point(line.p1)
                p2 = line.p2
            else:
                p1 = line.p1
                p2 = get_proj_point(line.p2)
            projected_lines.append(Line(p1, plane_point))
            yield Line(plane_point, p2)
        elif line.minz < last_z < line.maxz:
            plane = Plane((0, 0, last_z), (0, 0, 1, 'v'))
            cp = plane.intersect_point(line.dir, line.p1)[0]
            # we can be sure that there is an intersection
            if line.p1[2] > last_z:
                p1, p2 = cp, line.p2
            else:
                p1, p2 = line.p1, cp
            projected_lines.append(Line(p1, p2))
        else:
            if line.maxz <= z:
                # the line is completely below z
                projected_lines.append(Line(get_proj_point(line.p1),
                        get_proj_point(line.p2)))
            elif line.minz >= z:
                projected_lines.append(line)
            else:
                log.warn("Unexpected condition 'get_lines_layer': " + \
                        "%s / %s / %s / %s" % (line.p1, line.p2, z, last_z))
    # process all projected lines
    for line in projected_lines:
        points = []
        if step_width is None:
            points.append(line.p1)
            points.append(line.p2)
        else:
            if isiterable(step_width):
                steps = step_width
            else:
                steps = floatrange(0.0, line.len, inc=step_width)
            for step in steps:
                next_point = padd(line.p1, pmul(line.dir, step))
                points.append(next_point)
        yield points

def _get_sorted_polygons(models, callback=None):
    # Sort the polygons according to their directions (first inside, then
    # outside. This reduces the problem of break-away pieces.
    inner_polys = []
    outer_polys = []
    for model in models:
        for poly in model.get_polygons():
            if poly.get_area() <= 0:
                inner_polys.append(poly)
            else:
                outer_polys.append(poly)
    inner_sorter = PolygonSorter(inner_polys, callback=callback)
    outer_sorter = PolygonSorter(outer_polys, callback=callback)
    return inner_sorter.get_polygons() + outer_sorter.get_polygons()

def get_lines_grid(models, (low, high), layer_distance, line_distance=None,
        step_width=None, milling_style=MILLING_STYLE_CONVENTIONAL,
        start_position=START_Z, pocketing_type=POCKETING_TYPE_NONE,
        callback=None):
    # the lower limit is never below the model
    polygons = _get_sorted_polygons(models, callback=callback)
    if polygons:
        low_limit_lines = min([polygon.minz for polygon in polygons])
        low[2] = max(low[2], low_limit_lines)
    # calculate pockets
    if pocketing_type != POCKETING_TYPE_NONE:
        if not callback is None:
            callback(text="Generating pocketing polygons ...")
        polygons = get_pocketing_polygons(polygons, line_distance,
                pocketing_type, callback=callback)
    # extract lines in correct order from all polygons
    lines = []
    for polygon in polygons:
        if callback:
            callback()
        if polygon.is_closed and \
                (milling_style == MILLING_STYLE_CONVENTIONAL):
            polygon = polygon.copy()
            polygon.reverse()
        for line in polygon.get_lines():
            lines.append(line)
    if isiterable(layer_distance):
        layers = layer_distance
    elif layer_distance is None:
        # only one layer
        layers = [low[2]]
    else:
        layers = floatrange(low[2], high[2], inc=layer_distance,
                reverse=bool(start_position & START_Z))
    # turn the generator into a list - otherwise the slicing fails
    layers = list(layers)
    last_z = None
    if layers:
        # the upper layers are used for PushCutter operations
        for z in layers[:-1]:
            if callback:
                callback()
            yield get_lines_layer(lines, z, last_z=last_z, step_width=None,
                    milling_style=milling_style)
            last_z = z
        # the last layer is used for a DropCutter operation
        if callback:
            callback()
        yield get_lines_layer(lines, layers[-1], last_z=last_z,
                step_width=step_width, milling_style=milling_style)


def get_pocketing_polygons(polygons, offset, pocketing_type, callback=None):
    try:
        import pycam.Toolpath.LibArea
        use_libarea = True
    except ImportError:
        use_libarea = False
    if use_libarea:
        _log.debug("Using libarea pocketing algorithm")
        poly = pycam.Toolpath.LibArea._pocket_model(polygons)
    else:
        _log.info("Failed to load libarea library.")
        poly = get_pocketing_polygons_simple(polygons, offset, pocketing_type,
                callback)
    return poly


def get_pocketing_polygons_simple(polygons, offset, pocketing_type, callback=None):
    pocketing_limit = 1000
    base_polygons = []
    other_polygons = []
    if pocketing_type == POCKETING_TYPE_HOLES:
        # go inwards
        offset *= -1
        for poly in polygons:
            if poly.is_closed and poly.is_outer():
                base_polygons.append(poly)
            else:
                other_polygons.append(poly)
    elif pocketing_type == POCKETING_TYPE_MATERIAL:
        for poly in polygons:
            if poly.is_closed and not poly.is_outer():
                base_polygons.append(poly)
            else:
                other_polygons.append(poly)
    else:
        _log.warning("Invalid pocketing type given: %d" % str(pocketing_type))
        return polygons
    # For now we use only the polygons that do not surround any other
    # polygons. Sorry - the pocketing is currently very simple ...
    base_filtered_polygons = []
    for candidate in base_polygons:
        if callback and callback():
            # we were interrupted
            return polygons
        for other in other_polygons:
            if candidate.is_polygon_inside(other):
                break
        else:
            base_filtered_polygons.append(candidate)
    # start the pocketing for all remaining polygons
    pocket_polygons = []
    for base_polygon in base_filtered_polygons:
        pocket_polygons.append(base_polygon)
        current_queue = [base_polygon]
        next_queue = []
        pocket_depth = 0
        while current_queue and (pocket_depth < pocketing_limit):
            if callback and callback():
                return polygons
            for poly in current_queue:
                result = poly.get_offset_polygons(offset)
                pocket_polygons.extend(result)
                next_queue.extend(result)
                pocket_depth += 1
            current_queue = next_queue
            next_queue = []
    return pocket_polygons

