bl_info = {
    "name": "MMD to Funscript Converter (Ultimate Edition)",
    "author": "Gemini",
    "version": (1, 8),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar (N-Panel) > MMD Funscript",
    "description": "자동 범위 활성화 시에도 UI 레이아웃이 무너지지 않고 입력창만 비활성화되는 버전",
    "category": "Animation",
}

import bpy
import json
import math
import os

TARGET_BONES = [
    "센터", "センター", "Center", "center", 
    "하반신", "下半身", "Lower Body", "lower body", 
    "허리", "Waist", "waist"
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
        description="체크 시 1프레임 정밀 시뮬레이션을 활성화하여 한계 각도 탈출 시 부드럽게 감속 추적합니다",
        default=False
    )
    smooth_frames: bpy.props.IntProperty(
        name="지연 추적 프레임",
        default=3, min=1, max=100
    )
    
    range_mode: bpy.props.EnumProperty(
        name="범위 지정 방식",
        items=[
            ('TOTAL', '전체 범위 크기 (Width)', '지정한 총 각도 크기를 균등 분할합니다 (예: 90도 -> -45~45도)'),
            ('MINMAX', '최소/최대 직접 지정', '최소 각도와 최대 각도를 개별적으로 입력합니다')
        ],
        default='TOTAL'
    )
    
    use_auto_range: bpy.props.BoolProperty(
        name="자동 범위 최적화 (Auto-Range)",
        description="체크 시 애니메이션 전체를 사전 스캔하여 가동 범위(최댓값 대칭)를 자동으로 빌드합니다",
        default=False
    )
    
    export_pitch: bpy.props.BoolProperty(name="Pitch (X축) 활성화", default=True)
    export_roll: bpy.props.BoolProperty(name="Roll (Y축) 활성화", default=True)
    export_twist: bpy.props.BoolProperty(name="Twist (Z축) 활성화", default=True)
    
    invert_pitch: bpy.props.BoolProperty(name="Pitch 뒤집기 (정방향화)", default=False)
    invert_roll: bpy.props.BoolProperty(name="Roll 뒤집기 (정방향화)", default=False)
    invert_twist: bpy.props.BoolProperty(name="Twist 뒤집기 (정방향화)", default=False)
    
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
    
    def normalize_angle_bounds(self, angle_rad, min_deg, max_deg, invert):
        deg = math.degrees(angle_rad)
        deg = (deg + 180) % 360 - 180
        
        out_of_bounds = (deg < min_deg or deg > max_deg)
        deg = max(min_deg, min(max_deg, deg))
        
        if max_deg == min_deg:
            pos = 50.0
        else:
            pos = ((deg - min_deg) / (max_deg - min_deg)) * 100.0
            
        final_pos = (pos if invert else 100.0 - pos)
        return final_pos, out_of_bounds

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
        
        # --- 자동 범위 최적화 사전 스캔 ---
        calc_pitch_min, calc_pitch_max = -22.5, 22.5
        calc_roll_min, calc_roll_max = -45.0, 45.0
        calc_twist_min, calc_twist_max = -90.0, 90.0
        
        if props.use_auto_range:
            max_p_abs, max_r_abs, max_t_abs = 0.0, 0.0, 0.0
            for f in range(start_frame, end_frame + 1):
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
                    
                p_deg = (math.degrees(p_rad) + 180) % 360 - 180
                r_deg = (math.degrees(r_rad) + 180) % 360 - 180
                t_deg = (math.degrees(t_rad) + 180) % 360 - 180
                
                max_p_abs = max(max_p_abs, abs(p_deg))
                max_r_abs = max(max_r_abs, abs(r_deg))
                max_t_abs = max(max_t_abs, abs(t_deg))
                
            max_p_abs = max(1.0, max_p_abs)
            max_r_abs = max(1.0, max_r_abs)
            max_t_abs = max(1.0, max_t_abs)
            
            calc_pitch_min, calc_pitch_max = -max_p_abs, max_p_abs
            calc_roll_min, calc_roll_max = -max_r_abs, max_r_abs
            calc_twist_min, calc_twist_max = -max_t_abs, max_t_abs
        else:
            if props.range_mode == 'TOTAL':
                calc_pitch_min, calc_pitch_max = -props.pitch_range/2.0, props.pitch_range/2.0
                calc_roll_min, calc_roll_max = -props.roll_range/2.0, props.roll_range/2.0
                calc_twist_min, calc_twist_max = -props.twist_range/2.0, props.twist_range/2.0
            else:
                calc_pitch_min, calc_pitch_max = props.pitch_min, props.pitch_max
                calc_roll_min, calc_roll_max = props.roll_min, props.roll_max
                calc_twist_min, calc_twist_max = props.twist_min, props.twist_max

        # --- 메인 데이터 추출 루프 ---
        pitch_actions, roll_actions, twist_actions = [], [], []
        
        if props.use_smoothing:
            prev_pitch, prev_roll, prev_twist = 50.0, 50.0, 50.0
            pitch_lag, roll_lag, twist_lag = False, False, False
            max_step = 100.0 / max(1, props.smooth_frames)
            
            for f in range(start_frame, end_frame + 1):
                scene.frame_set(f)
                time_ms = int((f / fps) * 1000)
                
                mat = target_bone.matrix_basis if props.tracking_mode == 'LOCAL' else target_bone.matrix
                v_right = mat.col[0].xyz.normalized()
                v_up = mat.col[1].xyz.normalized()
                
                if props.tracking_mode == 'LOCAL':
                    pitch_rad = math.atan2(v_up.z, v_up.y)
                    roll_rad = math.atan2(v_up.x, v_up.y)
                    twist_rad = math.atan2(-v_right.z, v_right.x)
                else:
                    pitch_rad = math.atan2(v_up.y, v_up.z)
                    roll_rad = math.atan2(v_up.x, v_up.z)
                    twist_rad = math.atan2(v_right.y, v_right.x)
                
                t_pitch, out_pitch = self.normalize_angle_bounds(pitch_rad, calc_pitch_min, calc_pitch_max, props.invert_pitch)
                if f == start_frame:
                    curr_pitch, pitch_lag = t_pitch, out_pitch
                else:
                    if out_pitch: pitch_lag = True
                    if pitch_lag:
                        diff = t_pitch - prev_pitch
                        if abs(diff) <= max_step:
                            curr_pitch = t_pitch
                            if not out_pitch: pitch_lag = False
                        else:
                            curr_pitch = prev_pitch + math.copysign(max_step, diff)
                    else: curr_pitch = t_pitch
                prev_pitch = curr_pitch
                
                t_roll, out_roll = self.normalize_angle_bounds(roll_rad, calc_roll_min, calc_roll_max, props.invert_roll)
                if f == start_frame:
                    curr_roll, roll_lag = t_roll, out_roll
                else:
                    if out_roll: roll_lag = True
                    if roll_lag:
                        diff = t_roll - prev_roll
                        if abs(diff) <= max_step:
                            curr_roll = t_roll
                            if not out_roll: roll_lag = False
                        else:
                            curr_roll = prev_roll + math.copysign(max_step, diff)
                    else: curr_roll = t_roll
                prev_roll = curr_roll
                
                t_twist, out_twist = self.normalize_angle_bounds(twist_rad, calc_twist_min, calc_twist_max, props.invert_twist)
                if f == start_frame:
                    curr_twist, twist_lag = t_twist, out_twist
                else:
                    if out_twist: twist_lag = True
                    if twist_lag:
                        diff = t_twist - prev_twist
                        if abs(diff) <= max_step:
                            curr_twist = t_twist
                            if not out_twist: twist_lag = False
                        else:
                            curr_twist = prev_twist + math.copysign(max_step, diff)
                    else: curr_twist = t_twist
                prev_twist = curr_twist
                
                if (f - start_frame) % props.frame_step == 0:
                    if props.export_pitch: pitch_actions.append({"at": time_ms, "pos": int(round(curr_pitch))})
                    if props.export_roll: roll_actions.append({"at": time_ms, "pos": int(round(curr_roll))})
                    if props.export_twist: twist_actions.append({"at": time_ms, "pos": int(round(curr_twist))})
                    
        else:
            for f in range(start_frame, end_frame + 1, props.frame_step):
                scene.frame_set(f)
                time_ms = int((f / fps) * 1000)
                
                mat = target_bone.matrix_basis if props.tracking_mode == 'LOCAL' else target_bone.matrix
                v_right = mat.col[0].xyz.normalized()
                v_up = mat.col[1].xyz.normalized()
                
                if props.tracking_mode == 'LOCAL':
                    pitch_rad = math.atan2(v_up.z, v_up.y)
                    roll_rad = math.atan2(v_up.x, v_up.y)
                    twist_rad = math.atan2(-v_right.z, v_right.x)
                else:
                    pitch_rad = math.atan2(v_up.y, v_up.z)
                    roll_rad = math.atan2(v_up.x, v_up.z)
                    twist_rad = math.atan2(v_right.y, v_right.x)
                
                if props.export_pitch:
                    pos_x, _ = self.normalize_angle_bounds(pitch_rad, calc_pitch_min, calc_pitch_max, props.invert_pitch)
                    pitch_actions.append({"at": time_ms, "pos": int(round(pos_x))})
                if props.export_roll:
                    pos_y, _ = self.normalize_angle_bounds(roll_rad, calc_roll_min, calc_roll_max, props.invert_roll)
                    roll_actions.append({"at": time_ms, "pos": int(round(pos_y))})
                if props.export_twist:
                    pos_z, _ = self.normalize_angle_bounds(twist_rad, calc_twist_min, calc_twist_max, props.invert_twist)
                    twist_actions.append({"at": time_ms, "pos": int(round(pos_z))})
                    
        scene.frame_set(current_frame)
        
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

        self.report({'INFO'}, f"생성 완료 (AutoRange: {props.use_auto_range}): {', '.join(files_created)}")
        return {'FINISHED'}


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
        
        # 글로벌 지연 설정 박스
        box_s = layout.box()
        box_s.label(text="글로벌 옵션 (전체 축 공유)", icon='PROPERTIES')
        box_s.prop(props, "use_smoothing")
        if props.use_smoothing:
            box_s.prop(props, "smooth_frames")
            
        # 범위 제어 정책 박스
        box_m = layout.box()
        box_m.label(text="가동 범위 판단 기준", icon='CONSTRAINT')
        box_m.prop(props, "use_auto_range")
        
        # [반영] 자동 범위를 켜도 방식 선택 창은 비활성화될 뿐, 숨겨지지 않음
        row_mode = box_m.row()
        if props.use_auto_range:
            row_mode.enabled = False
        row_mode.prop(props, "range_mode")
            
        layout.label(text="축별 개별 활성화 및 뒤집기 옵션:")
        
        # --- 1. Pitch Box ---
        box_p = layout.box()
        row_p = box_p.row()
        row_p.prop(props, "export_pitch")
        row_p.prop(props, "invert_pitch", text="축 방향 전환")
        
        # [핵심 수정] 하단 레이아웃을 숨기지 않고 값 입력 필드만 선택적으로 비활성화(Gray-out)
        input_col_p = box_p.column()
        if props.use_auto_range:
            input_col_p.enabled = False
            
        if props.range_mode == 'TOTAL':
            input_col_p.prop(props, "pitch_range", text="자동 연산 범위" if props.use_auto_range else "전체 범위 (도)")
        else:
            grid = input_col_p.grid_flow(columns=2, align=True)
            grid.prop(props, "pitch_min", text="최소 (자동)" if props.use_auto_range else "최소")
            grid.prop(props, "pitch_max", text="최대 (자동)" if props.use_auto_range else "최대")
        
        # --- 2. Roll Box ---
        box_r = layout.box()
        row_r = box_r.row()
        row_r.prop(props, "export_roll")
        row_r.prop(props, "invert_roll", text="축 방향 전환")
        
        input_col_r = box_r.column()
        if props.use_auto_range:
            input_col_r.enabled = False
            
        if props.range_mode == 'TOTAL':
            input_col_r.prop(props, "roll_range", text="자동 연산 범위" if props.use_auto_range else "전체 범위 (도)")
        else:
            grid = input_col_r.grid_flow(columns=2, align=True)
            grid.prop(props, "roll_min", text="최소 (자동)" if props.use_auto_range else "최소")
            grid.prop(props, "roll_max", text="최대 (자동)" if props.use_auto_range else "max")
        
        # --- 3. Twist Box ---
        box_t = layout.box()
        row_t = box_t.row()
        row_t.prop(props, "export_twist")
        row_t.prop(props, "invert_twist", text="축 방향 전환")
        
        input_col_t = box_t.column()
        if props.use_auto_range:
            input_col_t.enabled = False
            
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