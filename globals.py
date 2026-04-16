import re
import os
import ifcopenshell

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


def round_quantities(model):
    """
    IFC 모델 내의 모든 물리적 수량(IfcPhysicalSimpleQuantity) 값을 소수점 3째 자리까지 반올림합니다.
    """
    for quantity in model.by_type("IfcPhysicalSimpleQuantity"):
        if quantity.is_a("IfcQuantityLength") and getattr(quantity, "LengthValue", None) is not None:
            quantity.LengthValue = round(float(quantity.LengthValue), 3)
        elif quantity.is_a("IfcQuantityArea") and getattr(quantity, "AreaValue", None) is not None:
            quantity.AreaValue = round(float(quantity.AreaValue), 3)
        elif quantity.is_a("IfcQuantityVolume") and getattr(quantity, "VolumeValue", None) is not None:
            quantity.VolumeValue = round(float(quantity.VolumeValue), 3)
        elif quantity.is_a("IfcQuantityWeight") and getattr(quantity, "WeightValue", None) is not None:
            quantity.WeightValue = round(float(quantity.WeightValue), 3)
        elif quantity.is_a("IfcQuantityTime") and getattr(quantity, "TimeValue", None) is not None:
            quantity.TimeValue = round(float(quantity.TimeValue), 3)
        elif quantity.is_a("IfcQuantityCount") and getattr(quantity, "CountValue", None) is not None:
            quantity.CountValue = round(float(quantity.CountValue), 3)
    return model
