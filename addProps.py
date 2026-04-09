import ifcopenshell
import ifcopenshell.guid
import re
import os

def sort_ifc_file(file_path):
    """IFC 파일의 DATA 섹션을 Express ID 기준으로 정렬하여 덮어씁니다."""
    if not os.path.exists(file_path):
        return
        
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    header_content, data_content, footer_content = [], [], []
    is_data_section = False
    id_pattern = re.compile(r'^#(\d+)=')

    for line in lines:
        stripped = line.strip()
        if stripped == "DATA;":
            is_data_section = True
            header_content.append(line)
            continue
        elif stripped == "ENDSEC;" and is_data_section:
            is_data_section = False
            footer_content.append(line)
            continue
            
        if is_data_section:
            match = id_pattern.match(stripped)
            if match:
                data_content.append((int(match.group(1)), line))
            else:
                if data_content:
                    last_id, last_text = data_content[-1]
                    data_content[-1] = (last_id, last_text + line)
                else:
                    header_content.append(line)
        else:
            if not data_content:
                header_content.append(line)
            else:
                footer_content.append(line)

    data_content.sort(key=lambda x: x[0])

    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(header_content)
        for _, content in data_content:
            f.write(content)
        f.writelines(footer_content)

def add_properties_to_ifc(input_file_path, output_file_path, express_ids, properties_data):
    """
    특정 객체들의 Express ID 배열과 Pset 정보를 바탕으로 IFC 파일에 속성을 주입합니다.
    """
    model = ifcopenshell.open(input_file_path)
    
    owner_history_list = model.by_type("IfcOwnerHistory")
    owner_history = owner_history_list[0] if owner_history_list else None

    def cast_value(value):
        try:
            val_str = str(value).lower()
            if val_str in ['true', 'false']:
                return val_str == 'true', "IfcBoolean"
            if str(value).isdigit() or (str(value).startswith('-') and str(value)[1:].isdigit()):
                return int(value), "IfcInteger"
            if '.' in str(value):
                return float(value), "IfcReal"
        except ValueError:
            pass
        return str(value), "IfcLabel"

    def create_val_ent(value):
        val, ifc_type = cast_value(value)
        return model.create_entity(ifc_type, val)

    # 1. 대상 객체들 조회
    target_elements = []
    for exp_id in express_ids:
        try:
            element = model.by_id(int(exp_id))
            if element.is_a("IfcObject"):
                target_elements.append(element)
        except Exception:
            print(f"[Warning] Element with Express ID {exp_id} not found.")

    if not target_elements:
        print("[Warning] No valid elements found to add properties.")
        model.write(output_file_path)
        sort_ifc_file(output_file_path)
        return

    # 2. 추가/업데이트할 Pset들을 순회
    for pset_data in properties_data:
        pset_name = pset_data.get("name")
        props_list = pset_data.get("props", [])
        
        if not pset_name or not props_list:
            continue

        elements_with_existing_pset = []
        elements_without_pset = []

        # 객체들을 Pset 존재 여부에 따라 두 그룹으로 분류
        for element in target_elements:
            existing_pset = None
            existing_rel = None
            for rel in getattr(element, "IsDefinedBy", []):
                if rel.is_a("IfcRelDefinesByProperties"):
                    pset = rel.RelatingPropertyDefinition
                    if pset and pset.is_a("IfcPropertySet") and pset.Name == pset_name:
                        existing_pset = pset
                        existing_rel = rel
                        break
            
            if existing_pset:
                elements_with_existing_pset.append((element, existing_pset, existing_rel))
            else:
                elements_without_pset.append(element)

        # 이번 Pset에서 새로 생성할 프로퍼티들을 한 번만 만들고 공유하기 위한 캐시
        shared_props = {}

        # 그룹 A: 기존에 같은 이름의 Pset이 있는 객체들 (Update or Skip)
        # 기존 Pset과 Rel 인스턴스를 기준으로 그룹화하여, 업데이트 대상 객체들끼리만 새 Pset을 공유
        update_groups = {}
        for element, existing_pset, existing_rel in elements_with_existing_pset:
            key = (existing_pset, existing_rel)
            if key not in update_groups:
                update_groups[key] = []
            update_groups[key].append(element)

        for (existing_pset, existing_rel), elements_to_update in update_groups.items():
            existing_props = {p.Name: p for p in (existing_pset.HasProperties or [])}
            needs_update = False
            
            # 기존 프로퍼티를 복사해두고, 변경/추가되는 부분을 덮어씌움
            new_props_dict = dict(existing_props)
            
            for prop in props_list:
                prop_name = prop.get("name")
                prop_value = prop.get("value")
                new_val, new_type = cast_value(prop_value)
                
                if prop_name in existing_props:
                    existing_prop = existing_props[prop_name]
                    existing_val = existing_prop.NominalValue.wrappedValue if getattr(existing_prop, "NominalValue", None) else None
                    
                    if existing_val != new_val:
                        # 값이 변경된 경우 새로운 프로퍼티 생성 후 덮어쓰기
                        needs_update = True
                        if prop_name not in shared_props:
                            shared_props[prop_name] = model.create_entity("IfcPropertySingleValue", Name=prop_name, NominalValue=create_val_ent(prop_value), Unit=None)
                        new_props_dict[prop_name] = shared_props[prop_name]
                    # 값이 같은 경우 기존 프로퍼티 엔티티를 그대로 재사용 (needs_update = False 유지)
                else:
                    # 완전히 새로운 프로퍼티인 경우
                    needs_update = True
                    if prop_name not in shared_props:
                        shared_props[prop_name] = model.create_entity("IfcPropertySingleValue", Name=prop_name, NominalValue=create_val_ent(prop_value), Unit=None)
                    new_props_dict[prop_name] = shared_props[prop_name]
            
            if needs_update:
                # 1. 분리된 새 Pset 생성
                new_pset = model.create_entity(
                    "IfcPropertySet", 
                    GlobalId=ifcopenshell.guid.new(), 
                    OwnerHistory=owner_history, 
                    Name=pset_name, 
                    Description=existing_pset.Description, 
                    HasProperties=list(new_props_dict.values())
                )
                
                # 2. 업데이트된 객체들을 새 Pset에 연결하는 새 Rel 생성
                model.create_entity(
                    "IfcRelDefinesByProperties", 
                    GlobalId=ifcopenshell.guid.new(), 
                    OwnerHistory=owner_history, 
                    Name=None, 
                    Description=None, 
                    RelatedObjects=elements_to_update, 
                    RelatingPropertyDefinition=new_pset
                )
                
                # 3. 기존 Pset을 공유하던 기존 Rel에서 업데이트된 객체들을 제거 (완벽한 분리)
                old_related_objects = list(existing_rel.RelatedObjects)
                for elem in elements_to_update:
                    if elem in old_related_objects:
                        old_related_objects.remove(elem)
                
                if old_related_objects:
                    existing_rel.RelatedObjects = old_related_objects
                else:
                    # 더 이상 기존 Pset을 참조하는 객체가 없으면 스키마 위반을 막기 위해 제거
                    model.remove(existing_rel)
                    model.remove(existing_pset)

        # 그룹 B: 기존에 같은 이름의 Pset이 없는 객체들 (New Pset 한 번만 생성 및 다중 연결)
        if elements_without_pset:
            new_single_props = []
            for prop in props_list:
                prop_name = prop.get("name")
                prop_value = prop.get("value")
                
                # 그룹 A에서 생성된 프로퍼티가 있다면 재사용, 없으면 새로 생성하여 공유
                if prop_name not in shared_props:
                    shared_props[prop_name] = model.create_entity("IfcPropertySingleValue", Name=prop_name, NominalValue=create_val_ent(prop_value), Unit=None)
                new_single_props.append(shared_props[prop_name])
            
            new_pset = model.create_entity(
                "IfcPropertySet", 
                GlobalId=ifcopenshell.guid.new(), 
                OwnerHistory=owner_history, 
                Name=pset_name, 
                Description=None, 
                HasProperties=new_single_props
            )
            
            model.create_entity(
                "IfcRelDefinesByProperties", 
                GlobalId=ifcopenshell.guid.new(), 
                OwnerHistory=owner_history, 
                Name=None, 
                Description=None, 
                RelatedObjects=elements_without_pset, 
                RelatingPropertyDefinition=new_pset
            )

    # 파일 저장
    model.write(output_file_path)
    
    # 용량 최적화 및 뷰어 호환성을 위해 파일 라인(DATA 섹션) 정렬
    sort_ifc_file(output_file_path)