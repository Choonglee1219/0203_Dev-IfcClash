import logging
import os
import io
import json
import zipfile
import base64
import xml.etree.ElementTree as ET
from ifcclash.ifcclash import Clasher, ClashSettings


def detect_clashes(clash_sets, bcf_file_path):
    """
    Perform clash detection based on the provided clash sets and export to BCF.
    Returns the raw clash data (including exact coordinates).
    """
    settings = ClashSettings()
    settings.logger = logging.getLogger("Clash")
    settings.logger.setLevel(logging.DEBUG)
    settings.output = bcf_file_path

    # Initialize clasher and execute the process
    clasher = Clasher(settings)
    clasher.clash_sets = clash_sets
    clasher.clash()

    # BCF를 먼저 내보냅니다.
    clasher.export_bcfxml()

    # clasher.clash_sets에는 이미 'p1' (Clash Point) 좌표 정보가 포함되어 있습니다.
    # 이를 반환하여 후처리 단계에서 정확한 좌표 매핑에 사용합니다.
    total_clashes_initial = sum(len(cs.get("clashes", [])) for cs in clasher.clash_sets)

    print(f"""
    Initial clash detection complete. BCF created at: {bcf_file_path}
    Found potential clashes: {total_clashes_initial}
    """)
    
    return clasher.clash_sets


def post_process_bcf(bcf_file_path, raw_clash_data=None):
    """
    Post-process the BCF package to standardize filenames and inject snapshots.
    Also extracts exact clash point coordinates to a JSON file.
    """
    if not os.path.exists(bcf_file_path):
        print(f"Error: BCF file not found at {bcf_file_path}")
        return None, None
    
    # --- Build Clash Point Lookup Map ---
    clash_point_map = {}
    if raw_clash_data:
        for cs in raw_clash_data:
            if "clashes" in cs:
                for clash in cs["clashes"].values():
                    key = frozenset([clash["a_global_id"], clash["b_global_id"]])
                    clash_point_map[key] = clash["p1"]

    extracted_data = [] 
    dummy_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")

    # 1. 원본 ZIP 파일을 메모리로 완전히 읽기
    with open(bcf_file_path, "rb") as f:
        source_zip_bytes = f.read()

    new_zip_buffer = io.BytesIO()

    # 2. 메모리 상에서 원본 ZIP 읽기 및 새 ZIP 쓰기 병행
    with zipfile.ZipFile(io.BytesIO(source_zip_bytes), 'r') as zin, \
         zipfile.ZipFile(new_zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zout:
         
        in_namelist = zin.namelist()
        topics = {}
        root_files = []

        # 폴더 및 파일 트리 분류
        for name in in_namelist:
            parts = name.split('/')
            if len(parts) > 1 and parts[0] != '':
                guid = parts[0]
                if guid not in topics:
                    topics[guid] = []
                topics[guid].append(name)
            else:
                root_files.append(name)

        # 루트 파일 그대로 복사 (디렉토리 자체 제외)
        for name in root_files:
            if not name.endswith('/'):
                zout.writestr(name, zin.read(name))

        # 3. 메모리 내에서 토픽 순회 처리
        for topic_guid, files in topics.items():
            clash_set_name = "Unknown"
            guids = []
            
            markup_name = f"{topic_guid}/markup.bcf"
            bcfv_name = next((f for f in files if f.endswith('.bcfv')), None)

            # A. viewpoint.bcfv 수정 및 복사
            if bcfv_name:
                v_bytes = zin.read(bcfv_name)
                try:
                    v_tree = ET.parse(io.BytesIO(v_bytes))
                    v_root = v_tree.getroot()
                    
                    for elem in v_root.iter():
                        if elem.tag.endswith("Component") and "IfcGuid" in elem.attrib:
                            if elem.attrib["IfcGuid"] not in guids:
                                guids.append(elem.attrib["IfcGuid"])
                                
                    components_node = v_root.find("Components")
                    if components_node is not None:
                        selection_node = components_node.find("Selection")
                        component_guids = [] if selection_node is None else [comp.attrib["IfcGuid"] for comp in selection_node.findall("Component") if "IfcGuid" in comp.attrib]

                        existing_coloring = components_node.find("Coloring")
                        if existing_coloring is not None:
                            components_node.remove(existing_coloring)

                        coloring_node = ET.SubElement(components_node, "Coloring")
                        color_a = ET.SubElement(coloring_node, "Color", {"Color": "B3FF0000"})
                        color_b = ET.SubElement(coloring_node, "Color", {"Color": "B300FF00"})

                        if len(component_guids) >= 2:
                            ET.SubElement(color_a, "Component", {"IfcGuid": component_guids[0]})
                            ET.SubElement(color_b, "Component", {"IfcGuid": component_guids[1]})
                            
                    out_v_bytes = io.BytesIO()
                    v_tree.write(out_v_bytes, encoding="utf-8", xml_declaration=True)
                    zout.writestr(f"{topic_guid}/viewpoint.bcfv", out_v_bytes.getvalue())
                except Exception:
                    zout.writestr(f"{topic_guid}/viewpoint.bcfv", v_bytes)

            # B. markup.bcf 수정 및 복사
            if markup_name in files:
                m_bytes = zin.read(markup_name)
                try:
                    m_tree = ET.parse(io.BytesIO(m_bytes))
                    m_root = m_tree.getroot()
                    for elem in m_root.iter():
                        if elem.tag.endswith("Title"):
                            clash_set_name = elem.text
                            break
                            
                    viewpoints_node = m_root.find("Viewpoints")
                    if viewpoints_node is not None:
                        for child in list(viewpoints_node):
                            viewpoints_node.remove(child)
                        viewpoint = ET.SubElement(viewpoints_node, "Viewpoint")
                        viewpoint.text = "viewpoint.bcfv"
                        snapshot = ET.SubElement(viewpoints_node, "Snapshot")
                        snapshot.text = "snapshot.png"
                        
                    out_m_bytes = io.BytesIO()
                    m_tree.write(out_m_bytes, encoding="utf-8", xml_declaration=True)
                    zout.writestr(markup_name, out_m_bytes.getvalue())
                except Exception:
                    zout.writestr(markup_name, m_bytes)

            # C. 기타 남은 파일 복사 (스냅샷 및 기존 XML 제외)
            for f in files:
                if not f.endswith('/') and not f.endswith('.bcfv') and not f.endswith('markup.bcf') and not f.endswith('snapshot.png'):
                    zout.writestr(f, zin.read(f))

            # D. 공용 Snapshot 주입 (압축 생략을 통해 CPU 오버헤드 제거 및 처리 속도 향상)
            zout.writestr(f"{topic_guid}/snapshot.png", dummy_png, compress_type=zipfile.ZIP_STORED)

            # E. P1 정보 매핑 및 추출
            clash_point = None
            if len(guids) >= 2:
                key = frozenset([guids[0], guids[1]])
                clash_point = clash_point_map.get(key)

            extracted_data.append({
                "clash_set": clash_set_name,
                "clash_guid": topic_guid,
                "guid1": guids[0] if len(guids) > 0 else None,
                "guid2": guids[1] if len(guids) > 1 else None,
                "clash_point": clash_point
            })

    # 4. 메모리상의 완성된 ZIP을 디스크의 원본 파일에 단 1번 덮어쓰기
    with open(bcf_file_path, "wb") as f:
        f.write(new_zip_buffer.getvalue())

    # 5. Save extracted data to JSON
    json_output_path = os.path.splitext(bcf_file_path)[0] + "_clashes.json"
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(extracted_data, f, indent=4, ensure_ascii=False)

    print(f"""\
    Final BCF package created: {bcf_file_path}
    Clash data saved to: {json_output_path}
    """)
    
    return bcf_file_path, json_output_path

if __name__ == "__main__":
    ## Input Parameters
    bcf_file_path = r"C:\\01-Projects\\0203_Dev-IfcClash\\clash-detection.bcf"

    ## Define clash matrix
    input_file = r"C:\\01-Projects\\0203_Dev-IfcClash\\input.json"
    with open(input_file, "r") as clash_sets_file:
       clash_sets = json.loads(clash_sets_file.read())

    ## Function Execution
    # 원본 데이터(raw_clash_data)를 받아서 post_process_bcf에 전달
    raw_clash_data = detect_clashes(clash_sets, bcf_file_path)
    post_process_bcf(bcf_file_path, raw_clash_data)
