import cv2
import numpy as np
from collections import defaultdict, deque
from ultralytics import YOLO
import math
import csv
import time
import argparse
import sys
import os

# NEU: Import für die WhatsApp-Konvertierung
from moviepy import VideoFileClip 

# ==============================================================================
# 1. GLOBALE KONFIGURATIONEN & KONSTANTEN
# ==============================================================================
VEHICLE_CLASSES = {
    2: "Car", 
    3: "Motorcycle", 
    5: "Bus", 
    7: "Truck"
}

# Geometrie der Straße (in Metern) - ANGEPASST AUF DEIN VIDEO
ROAD_WIDTH_M = 5.5          # Geschätzte Breite deiner Wohnstraße in Metern

# Tracking & Transformation
BEV_SCALE = 10              # Maßstab: 10 Pixel entsprechen 1 Meter in der Vogelperspektive
HISTORY_LEN = 30            # Anzahl der Frames, über die die Geschwindigkeit gemessen wird
MIN_PIXELS_KPH = 20         # Minimale Pixel-Distanz, bevor eine Geschwindigkeit berechnet wird

# =========================================================
# DIE BLITZER-ZONE: ANGEPASST FÜR DEIN VIDEO
# =========================================================
ZONE_Y_MIN = 300  # Startet die Messung, wenn das Auto aus der Kurve kommt
ZONE_Y_MAX = 650  # Stoppt die Messung, bevor das Auto zu nah an der Linse ist

# ==============================================================================
# 2. PERSPEKTIVE (Bird's Eye View - BEV)
# ==============================================================================
# WICHTIG: ERSETZE DIESE WERTE MIT DEN ERGEBNISSEN AUS DEINEM calibrate.py TOOL!
SRC_ROAD = np.float32([
    [200, 700],   # Unten Links (Fahrbahnrand)
    [1000, 700],  # Unten Rechts (Fahrbahnrand)
    [800, 300],   # Oben Rechts (Fahrbahnrand in der Ferne / Ausfahrt weißes Haus)
    [400, 300]    # Oben Links (Fahrbahnrand in der Ferne)
])

def build_bev_transform(src_pts, road_width_m, scale):
    """
    Erstellt die Transformationsmatrix für die Vogelperspektive (Bird's Eye View).
    """
    pixel_width = int(road_width_m * scale)
    pixel_height = int(100 * scale) 
    
    dst_pts = np.float32([
        [0, pixel_height],
        [pixel_width, pixel_height],
        [pixel_width, 0],
        [0, 0]
    ])
    
    matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
    return matrix, pixel_width, pixel_height

def to_bev(pt, matrix):
    """Wandelt einen X/Y Punkt aus dem Kamerabild in die Vogelperspektive um."""
    pts = np.array([[[pt[0], pt[1]]]], dtype="float32")
    bev_pts = cv2.perspectiveTransform(pts, matrix)
    return float(bev_pts[0][0][0]), float(bev_pts[0][0][1])

# ==============================================================================
# 3. GRAFIK & BENUTZEROBERFLÄCHE (UI)
# ==============================================================================
def draw_dashed_line(img, pt1, pt2, color, thickness=1, gap=15):
    """Zeichnet eine gestrichelte Messlinie auf die Straße."""
    dist = math.hypot(pt2[0] - pt1[0], pt2[1] - pt1[1])
    pts = []
    
    for i in np.arange(0, dist, gap):
        r = i / dist
        x = int((pt1[0] * (1 - r) + pt2[0] * r) + 0.5)
        y = int((pt1[1] * (1 - r) + pt2[1] * r) + 0.5)
        pts.append((x, y))
        
    for i in range(0, len(pts) - 1, 2):
        cv2.line(img, pts[i], pts[i+1], color, thickness)

def get_speed_color(kph):
    """Bestimmt die Farbe basierend auf der Geschwindigkeit."""
    if kph < 30: 
        return (0, 255, 0)       
    elif kph < 50: 
        return (0, 255, 255)     
    else: 
        return (0, 0, 255)       

def draw_info_label(frame, x, y, text, color):
    """Zeichnet das Label über dem Auto."""
    font = cv2.FONT_HERSHEY_DUPLEX
    font_scale = 0.5
    thickness = 1
    
    (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    cv2.rectangle(frame, (x, y - text_height - 8), (x + text_width + 4, y), (0, 0, 0), -1)
    cv2.putText(frame, text, (x + 2, y - 4), font, font_scale, color, thickness)

# ==============================================================================
# 4. HAUPTPROGRAMM (Tracking & Geschwindigkeitsberechnung)
# ==============================================================================
def process_video(input_path, output_path, model_path, log_csv):
    print(f"[INFO] Lade YOLO Modell: {model_path}...")
    model = YOLO(model_path)
    
    print(f"[INFO] Öffne Videoquelle: {input_path}...")
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"[FEHLER] Video '{input_path}' konnte nicht geöffnet werden.")
        sys.exit(1)

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    if fps == 0 or math.isnan(fps): 
        fps = 30.0
        
    print(f"[INFO] Video Details: {width}x{height} | {fps:.2f} FPS | {total_frames} Frames")
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, int(fps), (width, height))

    bev_matrix, bev_w, bev_h = build_bev_transform(SRC_ROAD, ROAD_WIDTH_M, BEV_SCALE)
    
    track_history = defaultdict(lambda: deque(maxlen=HISTORY_LEN))
    speed_log = {}
    
    print(f"[INFO] Erstelle CSV Logdatei: {log_csv}...")
    with open(log_csv, mode='w', newline='') as csv_file:
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["Frame", "Track_ID", "Class", "Speed_KPH"])

        frame_idx = 0
        start_time = time.time()

        while True:
            success, frame = cap.read()
            if not success: 
                break
                
            frame_idx += 1
            current_speeds = []

            results = model.track(frame, persist=True, classes=list(VEHICLE_CLASSES.keys()), verbose=False)
            
            if results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.int().cpu().numpy()
                class_ids = results[0].boxes.cls.int().cpu().numpy()
                
                for box, track_id, cls_id in zip(boxes, track_ids, class_ids):
                    x1, y1, x2, y2 = map(int, box)
                    cx = int((x1 + x2) / 2)
                    cy = y2 
                    
                    # ---------------------------------------------------------
                    # MESSUNG NUR IN DER BLITZER-ZONE
                    # ---------------------------------------------------------
                    if cy > ZONE_Y_MIN and cy < ZONE_Y_MAX:
                        bev_x, bev_y = to_bev((cx, cy), bev_matrix)
                        track_history[track_id].append((bev_x, bev_y))
                        
                        kph = 0.0
                        if len(track_history[track_id]) >= 5:
                            pt1 = track_history[track_id][0]
                            pt2 = track_history[track_id][-1]
                            
                            dist_pixels = math.hypot(pt2[0] - pt1[0], pt2[1] - pt1[1])
                            
                            if dist_pixels > MIN_PIXELS_KPH:
                                dist_m = dist_pixels / BEV_SCALE
                                time_s = len(track_history[track_id]) / fps
                                kph = (dist_m / time_s) * 3.6
                                
                                if track_id in speed_log:
                                    kph = (speed_log[track_id] + kph) / 2
                                speed_log[track_id] = kph
                                current_speeds.append(kph)

                                if frame_idx % 10 == 0:
                                    cls_name = VEHICLE_CLASSES.get(cls_id, "Unknown")
                                    csv_writer.writerow([frame_idx, track_id, cls_name, round(kph, 2)])
                    else:
                        # Außerhalb der Zone frieren wir den letzten Wert ein
                        if track_id in speed_log:
                            current_speeds.append(speed_log[track_id])

                    # ---------------------------------------------------------
                    # ZEICHNEN
                    # ---------------------------------------------------------
                    display_kph = speed_log.get(track_id, 0.0)

                    color = get_speed_color(display_kph) if display_kph > 0 else (255, 255, 255)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    
                    class_name = VEHICLE_CLASSES.get(cls_id, "Car")
                    label_text = f"{class_name} ID:{track_id}"
                    if display_kph > 0:
                        label_text += f" {display_kph:.1f} km/h"
                        
                    draw_info_label(frame, x1, y1, label_text, color)

            # ---------------------------------------------------------
            # DASHBOARD UI
            # ---------------------------------------------------------
            overlay = frame.copy()
            cv2.rectangle(overlay, (20, 20), (320, 130), (0, 50, 0), -1)
            frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)
            
            elapsed = time.time() - start_time
            live_fps = frame_idx / elapsed if elapsed > 0 else 0
            avg_speed = sum(current_speeds)/len(current_speeds) if current_speeds else 0
            
            cv2.putText(frame, f"System FPS: {live_fps:.1f}", (40, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            cv2.putText(frame, f"Active Vehicles: {len(current_speeds)}", (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            cv2.putText(frame, f"Avg Flow Speed: {avg_speed:.1f} km/h", (40, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

            # Markierungslinien (gestrichelt)
            draw_dashed_line(frame, tuple(SRC_ROAD[0].astype(int)), tuple(SRC_ROAD[1].astype(int)), (0, 255, 255), 2)
            draw_dashed_line(frame, tuple(SRC_ROAD[3].astype(int)), tuple(SRC_ROAD[2].astype(int)), (0, 255, 255), 2)

            # Output speichern und Live-Vorschau anzeigen
            out.write(frame)
            cv2.imshow("Verkehrstracking Live", frame)
            
            if frame_idx % 30 == 0:
                print(f"[Verarbeitung] Frame {frame_idx}/{total_frames} | Fahrzeuge: {len(current_speeds)} | Avg Speed: {avg_speed:.1f} km/h")
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("[INFO] Verarbeitung durch Benutzer abgebrochen.")
                break

    # ---------------------------------------------------------
    # ABSCHLUSS & WHATSAPP KONVERTIERUNG
    # ---------------------------------------------------------
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    
    print(f"\n[INFO] OpenCV-Verarbeitung abgeschlossen.")
    print(f"[INFO] Konvertiere Video für WhatsApp (H.264)... Bitte warten, das kann einen Moment dauern.")
    
    # Pfad für die WhatsApp-Version generieren (hängt "_whatsapp" an den Dateinamen an)
    wa_output_path = output_path.replace(".mp4", "_whatsapp.mp4")
    
    try:
        # Konvertierung durchführen (logger=None verhindert, dass der Log im VB.NET Fenster zugespammt wird)
        clip = VideoFileClip(output_path)
        clip.write_videofile(wa_output_path, codec="libx264", audio=False, logger=None)
        clip.close()
        
        print(f"\n[ERFOLG] Verarbeitung vollständig abgeschlossen.")
        print(f"-> Original-Video: {output_path}")
        print(f"-> WhatsApp-Video: {wa_output_path}")
        print(f"-> Daten-Log:      {log_csv}")
    except Exception as e:
        print(f"\n[FEHLER] bei der WhatsApp-Konvertierung: {e}")
        print(f"-> Original-Video gespeichert unter: {output_path}")

# ==============================================================================
# 5. EINSTIEGSPUNKT & ARGUMENT PARSING
# ==============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YOLOv8 Verkehrstracking und Geschwindigkeitsmessung")
    parser.add_argument("--source", type=str, default="input.mp4", help="Pfad zum Eingabevideo")
    parser.add_argument("--output", type=str, default="output_speed.mp4", help="Pfad zum fertigen Video")
    parser.add_argument("--model", type=str, default="yolov8n.pt", help="Pfad zum YOLO Modell (z.B. yolov8n.pt)")
    parser.add_argument("--log", type=str, default="speed_log.csv", help="Name der CSV Logdatei")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.source) and not args.source.isdigit():
        print(f"[FEHLER] Die Datei '{args.source}' wurde nicht gefunden.")
        print("Bitte stelle sicher, dass das Video im selben Ordner liegt oder gib den vollen Pfad an.")
    else:
        process_video(args.source, args.output, args.model, args.log)
