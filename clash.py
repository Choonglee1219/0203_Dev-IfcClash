from ifcclash.ifcclash import Clasher, ClashSettings
import logging
import os
import json
import zipfile
import base64
import shutil
import xml.etree.ElementTree as ET


def detect_clashes(clash_sets, bcf_file_path):
    """
    Perform clash detection based on the provided clash sets and export to BCF.
    """
    settings = ClashSettings()
    settings.logger = logging.getLogger("Clash")
    settings.logger.setLevel(logging.DEBUG)
    settings.output = bcf_file_path

    # Initialize clasher and execute the process
    clasher = Clasher(settings)
    clasher.clash_sets = clash_sets
    clasher.clash()
    clasher.export_bcfxml()

    total_clashes = sum(len(cs.get("clashes", [])) for cs in clash_sets)

    print(f"""
    Clashes were detected and a BCF was Created: {bcf_file_path}
    Found clashes: {total_clashes}
    """)


def post_process_bcf(bcf_file_path):
    """
    Post-process the BCF package to standardize filenames and inject snapshots.
    """
    temp_dir = bcf_file_path + "_extracted"
    
    # 1. Decomporess the BCF package
    if not os.path.exists(bcf_file_path):
        print(f"Error: BCF file not found at {bcf_file_path}")
        return
    
    with zipfile.ZipFile(bcf_file_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)

    # 2. Iterate through each Topic folder (identified by GUID)
    for topic_guid in os.listdir(temp_dir):
        topic_path = os.path.join(temp_dir, topic_guid)
        if not os.path.isdir(topic_path): continue
        
        # A. Rename visualization files (.bcfv) to standard name
        bcfv_files = [f for f in os.listdir(topic_path) if f.endswith(".bcfv")]
        for f in bcfv_files:
            old_bcfv = os.path.join(topic_path, f)
            new_bcfv = os.path.join(topic_path, "viewpoint.bcfv")
            # Avoid error if the file is already named viewpoint.bcfv
            if old_bcfv != new_bcfv:
                if os.path.exists(new_bcfv): os.remove(new_bcfv)
                os.rename(old_bcfv, new_bcfv)

        # B. Create a dummy snapshot.png
        target_png = os.path.join(topic_path, "snapshot.png")
        dummy_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
        with open(target_png, "wb") as f:
            f.write(dummy_png)

        # C. Update XML internal paths in markup.bcf
        markup_path = os.path.join(topic_path, "markup.bcf")
        if not os.path.exists(markup_path): continue

        tree = ET.parse(markup_path)
        root = tree.getroot()
        
        viewpoints_node = root.find("Viewpoints")
        if viewpoints_node is not None:
            # Remove all existing Viewpoint / Snapshot
            for child in list(viewpoints_node):
                viewpoints_node.remove(child)
                
            # Standardize Viewpoint file reference (viewpoint.bcfv)
            viewpoint = ET.SubElement(viewpoints_node, "Viewpoint")
            viewpoint.text = "viewpoint.bcfv"
            
            # Standardize Snapshot file reference (snapshot.png)
            snapshot = ET.SubElement(viewpoints_node, "Snapshot")
            snapshot.text = "snapshot.png"

        tree.write(markup_path, encoding="utf-8", xml_declaration=True)

        # D. Update XML internal paths in viewpoint.bcfv
        bcfv_path = os.path.join(topic_path, "viewpoint.bcfv")
        if not os.path.exists(bcfv_path): continue

        tree = ET.parse(bcfv_path)
        root = tree.getroot()
        
        components_node = root.find("Components")
        if components_node is not None:
            selection_node = components_node.find("Selection")
            if selection_node is None:
                component_guids = []
            else:
                component_guids = [
                    comp.attrib["IfcGuid"]
                    for comp in selection_node.findall("Component")
                    if "IfcGuid" in comp.attrib
                ]

            existing_coloring = components_node.find("Coloring")
            if existing_coloring is not None:
                components_node.remove(existing_coloring)

            coloring_node = ET.SubElement(components_node, "Coloring")

            color_a = ET.SubElement(
                coloring_node,
                "Color",
                {"Color": "B3FF0000"}
            )
            
            color_b = ET.SubElement(
                coloring_node,
                "Color",
                {"Color": "B300FF00"}
            )

            if len(component_guids) >= 2:
                guid_a = component_guids[0]
                guid_b = component_guids[1]
                ET.SubElement(color_a, "Component", {"IfcGuid": guid_a})
                ET.SubElement(color_b, "Component", {"IfcGuid": guid_b})

        tree.write(bcfv_path, encoding="utf-8", xml_declaration=True)

    # 3. Re-compress the structure back into a BCF package
    with zipfile.ZipFile(bcf_file_path, 'w', zipfile.ZIP_DEFLATED) as new_zip:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, temp_dir)
                new_zip.write(full_path, rel_path)

    # 4. Cleanup: Remove temporary extraction directory
    shutil.rmtree(temp_dir)

    return print(f"""
    Final BCF package created: {bcf_file_path}
    """)


# ----- Main Space -----
if __name__ == "__main__":
    ## Input Parameters
    bcf_file_path = r"D:\\02-Dev\\0203_Dev-IfcClash\\clash-detection.bcf"

    ## Define clash matrix
    input_file = r"D:\\02-Dev\\0203_Dev-IfcClash\\input.json"
    with open(input_file, "r") as clash_sets_file:
       clash_sets = json.loads(clash_sets_file.read())


    ## Function Execution
    detect_clashes(clash_sets, bcf_file_path)
    post_process_bcf(bcf_file_path)