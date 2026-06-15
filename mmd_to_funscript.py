bl_info = {
    "name": "MMD to Funscript Converter (Ultimate Edition)",
    "author": "Gemini",
    "version": (2, 2),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar (N-Panel) > MMD Funscript",
    "description": "옆면 튐 현상 보정 및 양방향 정밀 뒤돌기 보정 반영 버전",
    "category": "Animation",
}

import bpy
import json
import math
import os

TARGET_BONES = [
    "센터", "センター", "Center", "center",
    "하반신", "下半身", "Lower Body", "lower body",
    "허리", "腰", "Waist", "waist", "Hips", "hips",
]

class MMD_FUNSCRIPT_Properties(bpy.types.PropertyGroup):
    target_dir: bpy.props.StringProperty(
        name="저장 경로",
        subtype='DIR_PATH'
    )
    file_name: bpy.props.StringProperty(
        name="파일 이름",
        default="motion"
    )
    frame_step: bpy.props.IntProperty(
        name="프레임 간격",
        default=5, min=1, max=30
    )
    tracking_mode: bpy.props.EnumProperty(
        name="추출 방식",
        items=[
            ('LOCAL', '캐릭터 기준 (Local)', '캐릭터의 몸을 기준으로 앞뒤/좌우/회전을 계산합니다'),
            ('GLOBAL', '세계/화면 기준 (Global)', '세계 격자(화면) 기준으로 계산합니다')
        ],
        default='LOCAL'
    )
    
    use_smoothing: bpy.props.BoolProperty(
        name="경계 지연 추적 사용",
        default=False
    )
    smooth_frames: bpy.props.IntProperty(
        name="지연 추적 프레임",
        default=3, min=1, max=100
    )
    
    range_mode: bpy.props.EnumProperty(
        name="범위 지정 방식",
        items=[
            ('TOTAL', '전체 범위 크기 (Width)', '지정한 총 각도 크기를 균등 분할합니다'),
            ('MINMAX', '최소/최대 직접 지정', '최소 각도와 최대 각도를 개별적으로 입력합니다')
        ],
        default='TOTAL'
    )
    
    use_auto_range: bpy.props.BoolProperty(
        name="자동 범위 최적화 (Auto-Range)",
        default=False
    )

    # [수정] '패스' 단어 제거 및 설명 직관화
    use_force_pre_scan: bpy.props.BoolProperty(
        name="전체 프레임 정밀 스캔",
        description="체크 시 프레임을 건너뛰지 않고 전체 스캔하여 뒤돌기 경계를 정밀하게 보정합니다",
        default=False
    )
    
    # 축 활성화 및 기본 반전
    export_pitch: bpy.props.BoolProperty(name="Pitch (X축) 활성화", default=True)
    export_roll: bpy.props.BoolProperty(name="Roll (Y축) 활성화", default=True)
    export_twist: bpy.props.BoolProperty(name="Twist (Z축) 활성화", default=True)
    
    invert_pitch: bpy.props.BoolProperty(name="Pitch 방향 뒤집기", default=False)
    invert_roll: bpy.props.BoolProperty(name="Roll 방향 뒤집기", default=False)
    invert_twist: bpy.props.BoolProperty(name="Twist 방향 뒤집기", default=False)
    
    # 축별 90도 초과 시 반전(Ping-Pong)
    fold_pitch: bpy.props.BoolProperty(name="Pitch 90도 반전", default=False)
    fold_roll: bpy.props.BoolProperty(name="Roll 90도 반전", default=False)
    fold_twist: bpy.props.BoolProperty(name="Twist 90도 반전", default=False)
    
    # 뒤돌기 보정 (90도 반전 하위 종속 옵션)
    shift_back_pitch: bpy.props.BoolProperty(
        name="Pitch 뒤돌기 보정",
        description="180도 경계면 및 복귀 시의 0도 경계면 튐 현상을 양방향으로 정밀 보정합니다",
        default=False
    )
    shift_back_roll: bpy.props.BoolProperty(
        name="Roll 뒤돌기 보정",
        description="180도 경계면 및 복귀 시의 0도 경계면 튐 현상을 양방향으로 정밀 보정합니다",
        default=False
    )
    shift_back_twist: bpy.props.BoolProperty(
        name="Twist 뒤돌기 보정",
        description="180도 경계면 및 복귀 시의 0도 경계면 튐 현상을 양방향으로 정밀 보정합니다",
        default=False
    )
    
    # 뒤돌기 판단 임계 프레임 변동 각도
    flip_thresh_pitch: bpy.props.FloatProperty(name="Pitch 임계 각도", default=270.0, min=1.0, max=360.0)
    flip_thresh_roll: bpy.props.FloatProperty(name="Roll 임계 각도", default=270.0, min=1.0, max=360.0)
    flip_thresh_twist: bpy.props.FloatProperty(name="Twist 임계 각도", default=270.0, min=1.0, max=360.0)
    
    # 수동 가동 범위 설정용
    pitch_range: bpy.props.FloatProperty(name="전체 범위 (도)", default=45.0, min=1.0, max=360.0)
    roll_range: bpy.props.FloatProperty(name="전체 범위 (도)", default=90.0, min=1.0, max=360.0)
    twist_range: bpy.props.FloatProperty(name="전체 범위 (도)", default=180.0, min=1.0, max=360.0)
    
    pitch_min: bpy.props.FloatProperty(name="최소 각도", default=-22.5)
    pitch_max: bpy.props.FloatProperty(name="최대 각도", default=22.5)
    roll_min: bpy.props.FloatProperty(name="최소 각도", default=-45.0)
    roll_max: bpy.props.FloatProperty(name="최대 각도", default=45.0)
    twist_min: bpy.props.FloatProperty(name="최소 각도", default=-90.0)
    twist_max: bpy.props.FloatProperty(name="최대 각도", default=90.0)


class MMD_OT_ExportFunscript(bpy.types.Operator):
    bl_idname = "mmd.export_funscript"
    bl_label = "Funscript 추출 시작"
    
    def process_backwards_shift(self, raw_angles, use_shift, thresh):
        """양방향 정밀 복귀 판정을 적용하여 후면 상태에서 정면으로 돌아올 때의 측면 튐 현상까지 완벽히 보정합니다."""
        if not use_shift or len(raw_angles) < 2:
            return raw_angles
            
        processed = []
        in_back_mode = True if abs(raw_angles[0]) > 90 else False
        
        for i in range(len(raw_angles)):
            if i > 0:
                if not in_back_mode:
                    # 1. 정면 모드: 원시 각도가 임계값 넘게 튀면(180도 경계 교차) 후면 모드 진입
                    if abs(raw_angles[i] - raw_angles[i-1]) > thresh:
                        in_back_mode = True
                else:
                    # 2. 후면 모드: 변환 각도 공간에서의 차이가 임계값을 넘으면(정면 복귀/0도 경계 교차) 후면 모드 해제
                    prev_shifted = raw_angles[i-1] - 180 if raw_angles[i-1] > 0 else raw_angles[i-1] + 180
                    curr_shifted = raw_angles[i] - 180 if raw_angles[i] > 0 else raw_angles[i] + 180
                    if abs(curr_shifted - prev_shifted) > thresh:
                        in_back_mode = False
            
            deg = raw_angles[i]
            # 후면 상태가 유지될 때는 90도 제한 없이 상시 변환을 적용하여 연속성을 보장합니다
            if in_back_mode:
                deg = deg - 180 if deg > 0 else deg + 180
            processed.append(deg)
            
        return processed

    def generate_axis_positions(self, processed_degs, min_deg, max_deg, invert, use_fold, use_smoothing, smooth_frames):
        positions = []
        prev_pos = 50.0
        lagging = False
        max_step = 100.0 / max(1, smooth_frames)
        
        for i, deg in enumerate(processed_degs):
            if use_fold:
                if deg > 90.0: deg = 180.0 - deg
                elif deg < -90.0: deg = -180.0 - deg
                
            deg_clamped = max(min_deg, min(max_deg, deg))
            out_of_bounds = (deg < min_deg or deg > max_deg)
            
            if max_deg == min_deg:
                pos = 50.0
            else:
                pos = ((deg_clamped - min_deg) / (max_deg - min_deg)) * 100.0
                
            target_pos = (pos if invert else 100.0 - pos)
            
            if use_smoothing:
                if i == 0:
                    curr_pos = target_pos
                    lagging = out_of_bounds
                else:
                    if out_of_bounds: lagging = True
                    if lagging:
                        diff = target_pos - prev_pos
                        if abs(diff) <= max_step:
                            curr_pos = target_pos
                            if not out_of_bounds: lagging = False
                        else:
                            curr_pos = prev_pos + math.copysign(max_step, diff)
                    else:
                        curr_pos = target_pos
            else:
                curr_pos = target_pos
                
            positions.append(curr_pos)
            prev_pos = curr_pos
            
        return positions

    def execute(self, context):
        props = context.scene.mmd_funscript_props
        obj = context.active_object
        
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "아머처(Armature) 객체를 선택해주세요.")
            return {'CANCELLED'}
        if not props.target_dir:
            self.report({'ERROR'}, "파일을 저장할 디렉토리를 지정해주세요.")
            return {'CANCELLED'}

        target_bone = None
        for bone_name in TARGET_BONES:
            if bone_name in obj.pose.bones:
                target_bone = obj.pose.bones[bone_name]
                break
                
        if not target_bone:
            self.report({'ERROR'}, "하반신 관련 뼈를 찾을 수 없습니다.")
            return {'CANCELLED'}
            
        scene = context.scene
        start_frame = scene.frame_start
        end_frame = scene.frame_end
        fps = scene.render.fps / scene.render.fps_base
        current_frame = scene.frame_current
        
        # [수정] 용어 정리 반영 (전체 프레임 정밀 스캔 활성화 체크)
        use_pre_scan = props.use_auto_range or props.use_force_pre_scan

        pitch_actions, roll_actions, twist_actions = [], [], []

        if use_pre_scan:
            # --- 루트 A: 정밀 스캔 (전체 프레임 연속 연산) ---
            frames = list(range(start_frame, end_frame + 1))
            pitch_raw, roll_raw, twist_raw = [], [], []
            
            for f in frames:
                scene.frame_set(f)
                mat = target_bone.matrix_basis if props.tracking_mode == 'LOCAL' else target_bone.matrix
                v_right = mat.col[0].xyz.normalized()
                v_up = mat.col[1].xyz.normalized()
                
                if props.tracking_mode == 'LOCAL':
                    p_rad = math.atan2(v_up.z, v_up.y)
                    r_rad = math.atan2(v_up.x, v_up.y)
                    t_rad = math.atan2(-v_right.z, v_right.x)
                else:
                    p_rad = math.atan2(v_up.y, v_up.z)
                    r_rad = math.atan2(v_up.x, v_up.z)
                    t_rad = math.atan2(v_right.y, v_right.x)
                    
                pitch_raw.append((math.degrees(p_rad) + 180) % 360 - 180)
                roll_raw.append((math.degrees(r_rad) + 180) % 360 - 180)
                twist_raw.append((math.degrees(t_rad) + 180) % 360 - 180)
                
            pitch_proc = self.process_backwards_shift(pitch_raw, props.fold_pitch and props.shift_back_pitch, props.flip_thresh_pitch)
            roll_proc = self.process_backwards_shift(roll_raw, props.fold_roll and props.shift_back_roll, props.flip_thresh_roll)
            twist_proc = self.process_backwards_shift(twist_raw, props.fold_twist and props.shift_back_twist, props.flip_thresh_twist)
            
            if props.use_auto_range:
                max_p = max([abs(apply_fold_temp(d, props.fold_pitch)) for d in pitch_proc]) if pitch_proc else 1.0
                max_r = max([abs(apply_fold_temp(d, props.fold_roll)) for d in roll_proc]) if roll_proc else 1.0
                max_t = max([abs(apply_fold_temp(d, props.fold_twist)) for d in twist_proc]) if twist_proc else 1.0
                calc_p_min, calc_p_max = -max(1.0, max_p), max(1.0, max_p)
                calc_r_min, calc_r_max = -max(1.0, max_r), max(1.0, max_r)
                calc_t_min, calc_t_max = -max(1.0, max_t), max(1.0, max_t)
            else:
                if props.range_mode == 'TOTAL':
                    calc_p_min, calc_p_max = -props.pitch_range/2.0, props.pitch_range/2.0
                    calc_r_min, calc_r_max = -props.roll_range/2.0, props.roll_range/2.0
                    calc_t_min, calc_t_max = -props.twist_range/2.0, props.twist_range/2.0
                else:
                    calc_p_min, calc_p_max = props.pitch_min, props.pitch_max
                    calc_r_min, calc_r_max = props.roll_min, props.roll_max
                    calc_t_min, calc_t_max = props.twist_min, props.twist_max

            pitch_positions = self.generate_axis_positions(pitch_proc, calc_p_min, calc_p_max, props.invert_pitch, props.fold_pitch, props.use_smoothing, props.smooth_frames)
            roll_positions = self.generate_axis_positions(roll_proc, calc_r_min, calc_r_max, props.invert_roll, props.fold_roll, props.use_smoothing, props.smooth_frames)
            twist_positions = self.generate_axis_positions(twist_proc, calc_t_min, calc_t_max, props.invert_twist, props.fold_twist, props.use_smoothing, props.smooth_frames)
            
            for idx, f in enumerate(frames):
                if (f - start_frame) % props.frame_step == 0:
                    time_ms = int((f / fps) * 1000)
                    if props.export_pitch: pitch_actions.append({"at": time_ms, "pos": int(round(pitch_positions[idx]))})
                    if props.export_roll: roll_actions.append({"at": time_ms, "pos": int(round(roll_positions[idx]))})
                    if props.export_twist: twist_actions.append({"at": time_ms, "pos": int(round(twist_positions[idx]))})
        else:
            # --- 루트 B: 프레임 간격 점프 고속 싱글 패스 ---
            if props.range_mode == 'TOTAL':
                calc_p_min, calc_p_max = -props.pitch_range/2.0, props.pitch_range/2.0
                calc_r_min, calc_r_max = -props.roll_range/2.0, props.roll_range/2.0
                calc_t_min, calc_t_max = -props.twist_range/2.0, props.twist_range/2.0
            else:
                calc_p_min, calc_p_max = props.pitch_min, props.pitch_max
                calc_r_min, calc_r_max = props.roll_min, props.roll_max
                calc_t_min, calc_t_max = props.twist_min, props.twist_max

            prev_p_pos, prev_r_pos, prev_t_pos = 50.0, 50.0, 50.0
            p_lagging, r_lagging, t_lagging = False, False, False
            max_step = 100.0 / max(1, props.smooth_frames)
            is_first = True

            p_raw_prev, r_raw_prev, t_raw_prev = None, None, None
            p_in_back, r_in_back, t_in_back = False, False, False

            for f in range(start_frame, end_frame + 1, props.frame_step):
                scene.frame_set(f)
                mat = target_bone.matrix_basis if props.tracking_mode == 'LOCAL' else target_bone.matrix
                v_right = mat.col[0].xyz.normalized()
                v_up = mat.col[1].xyz.normalized()
                
                if props.tracking_mode == 'LOCAL':
                    p_deg = (math.degrees(math.atan2(v_up.z, v_up.y)) + 180) % 360 - 180
                    r_deg = (math.degrees(math.atan2(v_up.x, v_up.y)) + 180) % 360 - 180
                    t_deg = (math.degrees(math.atan2(-v_right.z, v_right.x)) + 180) % 360 - 180
                else:
                    p_deg = (math.degrees(math.atan2(v_up.y, v_up.z)) + 180) % 360 - 180
                    r_deg = (math.degrees(math.atan2(v_up.x, v_up.z)) + 180) % 360 - 180
                    t_deg = (math.degrees(math.atan2(v_right.y, v_right.x)) + 180) % 360 - 180
                    
                time_ms = int((f / fps) * 1000)

                # Pitch 계산
                if props.export_pitch:
                    if props.fold_pitch and props.shift_back_pitch:
                        if p_raw_prev is not None:
                            if not p_in_back:
                                if abs(p_deg - p_raw_prev) > props.flip_thresh_pitch:
                                    p_in_back = True
                            else:
                                prev_shifted = p_raw_prev - 180 if p_raw_prev > 0 else p_raw_prev + 180
                                curr_shifted = p_deg - 180 if p_deg > 0 else p_deg + 180
                                if abs(curr_shifted - prev_shifted) > props.flip_thresh_pitch:
                                    p_in_back = False
                        p_raw_prev = p_deg
                        if p_in_back: 
                            p_deg = p_deg - 180 if p_deg > 0 else p_deg + 180
                    
                    if props.fold_pitch:
                        if p_deg > 90.0: p_deg = 180.0 - p_deg
                        elif p_deg < -90.0: p_deg = -180.0 - p_deg
                    p_pos = 50.0 if calc_p_max == calc_p_min else ((max(calc_p_min, min(calc_p_max, p_deg)) - calc_p_min) / (calc_p_max - calc_p_min)) * 100.0
                    p_tgt = p_pos if props.invert_pitch else 100.0 - p_pos
                    if props.use_smoothing:
                        if is_first: p_curr, p_lagging = p_tgt, (p_deg < calc_p_min or p_deg > calc_p_max)
                        else:
                            if (p_deg < calc_p_min or p_deg > calc_p_max): p_lagging = True
                            if p_lagging:
                                diff = p_tgt - prev_p_pos
                                p_curr = prev_p_pos + math.copysign(max_step, diff) if abs(diff) > max_step else p_tgt
                                if abs(diff) <= max_step and not (p_deg < calc_p_min or p_deg > calc_p_max): p_lagging = False
                            else: p_curr = p_tgt
                    else: p_curr = p_tgt
                    pitch_actions.append({"at": time_ms, "pos": int(round(p_curr))})
                    prev_p_pos = p_curr

                # Roll 계산
                if props.export_roll:
                    if props.fold_roll and props.shift_back_roll:
                        if r_raw_prev is not None:
                            if not r_in_back:
                                if abs(r_deg - r_raw_prev) > props.flip_thresh_roll:
                                    r_in_back = True
                            else:
                                prev_shifted = r_raw_prev - 180 if r_raw_prev > 0 else r_raw_prev + 180
                                curr_shifted = r_deg - 180 if r_deg > 0 else r_deg + 180
                                if abs(curr_shifted - prev_shifted) > props.flip_thresh_roll:
                                    r_in_back = False
                        r_raw_prev = r_deg
                        if r_in_back: 
                            r_deg = r_deg - 180 if r_deg > 0 else r_deg + 180

                    if props.fold_roll:
                        if r_deg > 90.0: r_deg = 180.0 - r_deg
                        elif r_deg < -90.0: r_deg = -180.0 - r_deg
                    r_pos = 50.0 if calc_r_max == calc_r_min else ((max(calc_r_min, min(calc_r_max, r_deg)) - calc_r_min) / (calc_r_max - calc_r_min)) * 100.0
                    r_tgt = r_pos if props.invert_roll else 100.0 - r_pos
                    if props.use_smoothing:
                        if is_first: r_curr, r_lagging = r_tgt, (r_deg < calc_r_min or r_deg > calc_r_max)
                        else:
                            if (r_deg < calc_r_min or r_deg > calc_r_max): r_lagging = True
                            if r_lagging:
                                diff = r_tgt - prev_r_pos
                                r_curr = prev_r_pos + math.copysign(max_step, diff) if abs(diff) > max_step else r_tgt
                                if abs(diff) <= max_step and not (r_deg < calc_r_min or r_deg > calc_r_max): r_lagging = False
                            else: r_curr = r_tgt
                    else: r_curr = r_tgt
                    roll_actions.append({"at": time_ms, "pos": int(round(r_curr))})
                    prev_r_pos = r_curr

                # Twist 계산
                if props.export_twist:
                    if props.fold_twist and props.shift_back_twist:
                        if t_raw_prev is not None:
                            if not t_in_back:
                                if abs(t_deg - t_raw_prev) > props.flip_thresh_twist:
                                    t_in_back = True
                            else:
                                prev_shifted = t_raw_prev - 180 if t_raw_prev > 0 else t_raw_prev + 180
                                curr_shifted = t_deg - 180 if t_deg > 0 else t_deg + 180
                                if abs(curr_shifted - prev_shifted) > props.flip_thresh_twist:
                                    t_in_back = False
                        t_raw_prev = t_deg
                        if t_in_back: 
                            t_deg = t_deg - 180 if t_deg > 0 else t_deg + 180

                    if props.fold_twist:
                        if t_deg > 90.0: t_deg = 180.0 - t_deg
                        elif t_deg < -90.0: t_deg = -180.0 - t_deg
                    t_pos = 50.0 if calc_t_max == calc_t_min else ((max(calc_t_min, min(calc_t_max, t_deg)) - calc_t_min) / (calc_t_max - calc_t_min)) * 100.0
                    t_tgt = t_pos if props.invert_twist else 100.0 - t_pos
                    if props.use_smoothing:
                        if is_first: t_curr, t_lagging = t_tgt, (t_deg < calc_t_min or t_deg > calc_t_max)
                        else:
                            if (t_deg < calc_t_min or t_deg > calc_t_max): t_lagging = True
                            if t_lagging:
                                diff = t_tgt - prev_t_pos
                                t_curr = prev_t_pos + math.copysign(max_step, diff) if abs(diff) > max_step else t_tgt
                                if abs(diff) <= max_step and not (t_deg < calc_t_min or t_deg > calc_t_max): t_lagging = False
                            else: t_curr = t_tgt
                    else: t_curr = t_tgt
                    twist_actions.append({"at": time_ms, "pos": int(round(t_curr))})
                    prev_t_pos = t_curr

                is_first = False
                    
        scene.frame_set(current_frame)
        
        # 파일 저장 프로세스
        base_path = bpy.path.abspath(props.target_dir)
        custom_name = props.file_name.strip()
        files_created = []
        
        def save_script(actions, suffix):
            file_path = os.path.join(base_path, f"{custom_name}.{suffix}.funscript")
            data = {"version": "1.0", "inverted": False, "range": 100, "actions": actions}
            with open(file_path, 'w', encoding='utf-8') as fs:
                json.dump(data, fs, indent=4)
            files_created.append(f"{custom_name}.{suffix}.funscript")

        if props.export_pitch and pitch_actions: save_script(pitch_actions, "pitch")
        if props.export_roll and roll_actions: save_script(roll_actions, "roll")
        if props.export_twist and twist_actions: save_script(twist_actions, "twist")

        self.report({'INFO'}, f"생성 완료: {', '.join(files_created)}")
        return {'FINISHED'}

def apply_fold_temp(deg, use_fold):
    if use_fold:
        if deg > 90.0: return 180.0 - deg
        elif deg < -90.0: return -180.0 - deg
    return deg

class MMD_PT_FunscriptPanel(bpy.types.Panel):
    bl_label = "MMD to Funscript (Ultimate Edition)"
    bl_idname = "MMD_PT_funscript_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MMD Funscript'
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.mmd_funscript_props
        obj = context.active_object
        
        box = layout.box()
        if obj and obj.type == 'ARMATURE':
            box.label(text=f"모델: {obj.name}", icon='ARMATURE_DATA')
        else:
            box.label(text="아머처를 선택해주세요", icon='ERROR')
            
        col = layout.column(align=True)
        col.prop(props, "target_dir")
        col.prop(props, "file_name")
        col.prop(props, "frame_step")
        
        layout.separator()
        layout.prop(props, "tracking_mode")
        
        box_s = layout.box()
        box_s.label(text="글로벌 옵션 (전체 축 공유)", icon='PROPERTIES')
        box_s.prop(props, "use_smoothing")
        if props.use_smoothing:
            box_s.prop(props, "smooth_frames")
            
        box_m = layout.box()
        box_m.label(text="가동 범위 판단 및 스캔 방식", icon='CONSTRAINT')
        box_m.prop(props, "use_auto_range")
        box_m.prop(props, "use_force_pre_scan")
        
        row_mode = box_m.row()
        if props.use_auto_range:
            row_mode.enabled = False
        row_mode.prop(props, "range_mode")
            
        layout.label(text="축별 제어 옵션:")
        
        # --- 1. Pitch Box ---
        box_p = layout.box()
        row_p = box_p.row(align=True)
        row_p.prop(props, "export_pitch", text="Pitch")
        row_p.prop(props, "invert_pitch", text="방향 전환")
        row_p.prop(props, "fold_pitch", text="90도 반전")
        
        sub_p = box_p.column()
        sub_p.active = props.fold_pitch
        row_p_flip = sub_p.row(align=True)
        row_p_flip.prop(props, "shift_back_pitch", text="뒤돌기 보정")
        if props.shift_back_pitch:
            row_p_flip.prop(props, "flip_thresh_pitch", text="임계값")
        
        input_col_p = box_p.column()
        if props.use_auto_range: input_col_p.enabled = False
        if props.range_mode == 'TOTAL':
            input_col_p.prop(props, "pitch_range", text="자동 연산 범위" if props.use_auto_range else "전체 범위 (도)")
        else:
            grid = input_col_p.grid_flow(columns=2, align=True)
            grid.prop(props, "pitch_min", text="최소 (자동)" if props.use_auto_range else "최소")
            grid.prop(props, "pitch_max", text="최대 (자동)" if props.use_auto_range else "최대")
        
        # --- 2. Roll Box ---
        box_r = layout.box()
        row_r = box_r.row(align=True)
        row_r.prop(props, "export_roll", text="Roll")
        row_r.prop(props, "invert_roll", text="방향 전환")
        row_r.prop(props, "fold_roll", text="90도 반전")
        
        sub_r = box_r.column()
        sub_r.active = props.fold_roll
        row_r_flip = sub_r.row(align=True)
        row_r_flip.prop(props, "shift_back_roll", text="뒤돌기 보정")
        if props.shift_back_roll:
            row_r_flip.prop(props, "flip_thresh_roll", text="임계값")
        
        input_col_r = box_r.column()
        if props.use_auto_range: input_col_r.enabled = False
        if props.range_mode == 'TOTAL':
            input_col_r.prop(props, "roll_range", text="자동 연산 범위" if props.use_auto_range else "전체 범위 (도)")
        else:
            grid = input_col_r.grid_flow(columns=2, align=True)
            grid.prop(props, "roll_min", text="최소 (자동)" if props.use_auto_range else "최소")
            grid.prop(props, "roll_max", text="최대 (자동)" if props.use_auto_range else "최대")
        
        # --- 3. Twist Box ---
        box_t = layout.box()
        row_t = box_t.row(align=True)
        row_t.prop(props, "export_twist", text="Twist")
        row_t.prop(props, "invert_twist", text="방향 전환")
        row_t.prop(props, "fold_twist", text="90도 반전")
        
        sub_t = box_t.column()
        sub_t.active = props.fold_twist
        row_t_flip = sub_t.row(align=True)
        row_t_flip.prop(props, "shift_back_twist", text="뒤돌기 보정")
        if props.shift_back_twist:
            row_t_flip.prop(props, "flip_thresh_twist", text="임계값")
        
        input_col_t = box_t.column()
        if props.use_auto_range: input_col_t.enabled = False
        if props.range_mode == 'TOTAL':
            input_col_t.prop(props, "twist_range", text="자동 연산 범위" if props.use_auto_range else "전체 범위 (도)")
        else:
            grid = input_col_t.grid_flow(columns=2, align=True)
            grid.prop(props, "twist_min", text="최소 (자동)" if props.use_auto_range else "최소")
            grid.prop(props, "twist_max", text="최대 (자동)" if props.use_auto_range else "최대")
        
        layout.separator()
        layout.operator("mmd.export_funscript", icon='EXPORT', text="Funscript 파일 생성")


classes = (MMD_FUNSCRIPT_Properties, MMD_OT_ExportFunscript, MMD_PT_FunscriptPanel)

def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.mmd_funscript_props = bpy.props.PointerProperty(type=MMD_FUNSCRIPT_Properties)

def unregister():
    for cls in classes: bpy.utils.unregister_class(cls)
    del bpy.types.Scene.mmd_funscript_props

if __name__ == "__main__":
    register()
