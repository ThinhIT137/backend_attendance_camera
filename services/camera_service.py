def generate_camera_id(conn):
    cursor = conn.cursor()
    # Lấy ID lớn nhất hiện tại
    cursor.execute("SELECT cam_id FROM cameras ORDER BY cam_id DESC LIMIT 1")
    last_row = cursor.fetchone()
    
    if last_row:
        # Tách lấy phần số sau dấu gạch dưới
        last_id = last_row[0] # "camera_001"
        number = int(last_id.split('_')[1])
        new_number = number + 1
    else:
        new_number = 1
        
    # Thay :02d bằng :03d để hiển thị 3 chữ số (001, 002, ...)
    return f"camera_{new_number:03d}"