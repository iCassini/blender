import bpy
from bpy.types import Operator
from mathutils import Vector

def get_marker_coordinates_in_pixels(context, track, frame_number):
    width, height = context.space_data.clip.size
    # return the marker coordinates in relation to the clip
    marker = track.markers.find_frame(frame_number)
    vector = Vector((marker.co[0] * width, marker.co[1] * height))
    return vector


def marker_velocity(context, track, frame):
    marker_a = get_marker_coordinates_in_pixels(context, track, frame)
    marker_b = get_marker_coordinates_in_pixels(context, track, frame-1)
    marker_velocity = marker_a - marker_b
    return marker_velocity


def get_difference(track_slope, average_slope, axis):
    # return the difference between slope of last frame and the average slope before it
    difference = track_slope[axis] - average_slope[axis]
    # rather use abs difference, to be able to better compare the actual value
    difference = abs(difference)
    return difference

def get_slope(context, track, frame):
    v1 = marker_velocity(context, track, frame)
    v2 = marker_velocity(context, track, frame-1)
    slope = v1-v2
    return slope

def check_evaluation_time(track, frame, evaluation_time):
    # check each frame for the evaluation time
    list = []
    for f in range(frame-evaluation_time, frame):
        # if there are no markers for that frame, skip
        if not track.markers.find_frame(f):
            continue
        # it also doesnt make sense to use a track that is has no previous marker
        if not track.markers.find_frame(f-1):
            continue
        # the frame after the last track is muted, but still valid, so skip that
        if track.markers.find_frame(f).mute:
             continue
        if track.markers.find_frame(f-1).mute:
             continue
        # append frames to the list 
        list.append(f)
        # make sure there are no gaps in the list
    if len(list) == evaluation_time:
        return True

def get_valid_tracks(scene, tracks):
    valid_tracks = {}
    for t in tracks:
        list = []
        for f in range(scene.frame_start, scene.frame_end):
            if not t.markers.find_frame(f):
                continue
            if t.markers.find_frame(f).mute:
                continue
            if not t.markers.find_frame(f-1):
                continue
            list.append(f)
            valid_tracks[t] = list
    return valid_tracks


def get_average_slope(context, track, frame, evaluation_time):
    average = Vector().to_2d()
    for f in range(frame-evaluation_time, frame):
        average = get_slope(context, track, f)
        average += average
    average = average / evaluation_time
    return average


def filter_track_ends(context, threshold, evaluation_time):
    # compare the last frame's slope with the ones before, and if needed, mute it.
    tracks = context.space_data.clip.tracking.tracks
    valid_tracks = get_valid_tracks(context.scene, tracks)
    to_clean = {}
    for track, list in valid_tracks.items():
        f = list[-1] 
        # first get the slope of the current track on current frame
        track_slope = get_slope(context, track, f)
        # if the track is as long as the evaluation time, calculate the average slope
        if check_evaluation_time(track, f, evaluation_time):
            average_slope = Vector().to_2d()
            for i in range(f-evaluation_time, f):
                # get the slopes of all frames during the evaluation time
                av_slope = get_slope(context, track, i)
                average_slope += av_slope 
            average_slope = average_slope / evaluation_time
            # check abs difference for both values in the vector
            for i in [0,1]:
                # if the difference between average_slope and track_slope on any axis is above threshold,
                # add to the to_clean dictionary
                if not track in to_clean and get_difference(track_slope, average_slope, i) > threshold:
                    to_clean[track] = f
    # now we can disable the last frame of the identified tracks
    for track, frame in to_clean.items():
        print("cleaned ", track.name, "on frame ", frame)
        track.markers.find_frame(frame).mute=True
    return len(to_clean)


def filter_foreground(context, evaluation_time, threshold):
    # filter tracks that move a lot faster than others towards the end of the track
    tracks = context.space_data.clip.tracking.tracks
    valid_tracks = get_valid_tracks(context.scene, tracks)
    foreground = []
    for track, list in valid_tracks.items():
        f = list[-1]
        # first get the average of the last frame during evaluation time
        if check_evaluation_time(track, f, evaluation_time) and not track in foreground:
            track_average = get_average_slope(context, track, f, evaluation_time)
            # then get the average of all other tracks
            global_average = Vector().to_2d()
            currently_valid_tracks = []
            # first check if the other tracks are valid too.
            for t in tracks:
                if check_evaluation_time(t, f, evaluation_time) and not t == track:
                    currently_valid_tracks.append(t)
            for t in currently_valid_tracks:
                other_average = get_average_slope(context, t, f, evaluation_time)
                global_average += other_average
            global_average = global_average / len(currently_valid_tracks)
            print(track.name, f, track_average, global_average)
            for i in [0,1]:
                difference = get_difference(track_average, global_average, i) * evaluation_time
                print(track.name, i, difference)
                if difference > threshold:
                    foreground.append(track)
    for track in foreground:
        track.select = True


class CLIP_OT_filter_track_ends(Operator):
    '''Filter the Track for spikes at the end of a track'''
    bl_idname = "clip.filter_track_ends"
    bl_label = "Filter Track Ends"
    bl_options = {'REGISTER', 'UNDO'}
    
    evaluation_time = bpy.props.IntProperty(
        name="Evaluation Time",
        default=10,
        min=0,
        max=1000,
        description="The length of the last part of the track that should be filtered")

    threshold = bpy.props.IntProperty(
        name="Threshold",
        default=1,
        min=0,
        max=100,
        description="The threshold over which a marker is considered outlier")

    @classmethod
    def poll(cls, context):
        sc = context.space_data
        return (sc.type == 'CLIP_EDITOR') and sc.clip

    def execute(self, context):
        # first do a minimal cleanup
        bpy.ops.clip.clean_tracks(frames=3, error=0, action='DELETE_SEGMENTS')
        num_tracks = filter_track_ends(context, self.threshold, self.evaluation_time)
        self.report({'INFO'}, "Muted %d track ends" % num_tracks)
        return {'FINISHED'}


class CLIP_OT_filter_foreground(Operator):
    '''Filter Foreground Tracks with faster movement'''
    bl_idname = "clip.filter_foreground_track"
    bl_label = "Filter Foreground Tracks"
    bl_options = {'REGISTER', 'UNDO'}

    evaluation_time = bpy.props.IntProperty(
        name="Evaluation Time",
        default=20,
        min=0,
        max=1000,
        description="The length of the last part of the track that should be filtered")

    threshold = bpy.props.IntProperty(
        name="Threshold",
        default=2,
        min=0,
        max=100,
        description="The threshold over which a marker is considered outlier")

    @classmethod
    def poll(cls, context):
        sc = context.space_data
        return (sc.type == 'CLIP_EDITOR') and sc.clip

    def execute(self, context):
        scene = context.scene
        filter_foreground(context, self.evaluation_time, self.threshold)
        return {'FINISHED'}


def register():
    bpy.utils.register_class(CLIP_OT_filter_track_ends)
    bpy.utils.register_class(CLIP_OT_filter_foreground)

def unregister():
    bpy.utils.unregister_class(CLIP_OT_filter_track_ends)
    bpy.utils.unregister_class(CLIP_OT_filter_foreground)

if __name__ == "__main__":
    register()
