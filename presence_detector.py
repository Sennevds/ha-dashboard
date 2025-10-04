import cv2
import mediapipe as mp
import threading
import time
from typing import Callable, Optional


class PresenceDetector:
    """Detects human presence using webcam and person/pose detection."""
    
    def __init__(self, detection_confidence: float = 0.5, check_interval: float = 1.0, 
                 detection_mode: str = "face"):
        """
        Initialize the presence detector.
        
        Args:
            detection_confidence: Minimum confidence for detection (0.0 to 1.0)
            check_interval: Time between checks in seconds
            detection_mode: Detection mode - "face", "pose", or "both"
                - "face": Detect faces only (best for looking at tablet)
                - "pose": Detect people/body pose (best for nearby presence)
                - "both": Detect either face or pose (most sensitive)
        """
        self.detection_confidence = detection_confidence
        self.check_interval = check_interval
        self.detection_mode = detection_mode
        self.is_running = False
        self.person_present = False
        self.last_detection_time = 0
        self._thread: Optional[threading.Thread] = None
        self._callbacks = []
        
        # Initialize MediaPipe detectors based on mode
        if detection_mode in ["face", "both"]:
            self.mp_face_detection = mp.solutions.face_detection
            self.face_detection = self.mp_face_detection.FaceDetection(
                model_selection=0,  # 0 for short range (2m), 1 for full range (5m)
                min_detection_confidence=detection_confidence
            )
        else:
            self.face_detection = None
        
        if detection_mode in ["pose", "both"]:
            self.mp_pose = mp.solutions.pose
            self.pose_detection = self.mp_pose.Pose(
                static_image_mode=False,
                model_complexity=0,  # 0=lite, 1=full, 2=heavy
                min_detection_confidence=detection_confidence,
                min_tracking_confidence=detection_confidence
            )
        else:
            self.pose_detection = None
        
        self.camera: Optional[cv2.VideoCapture] = None
    
    def start(self):
        """Start the presence detection in a background thread."""
        if self.is_running:
            return
        
        self.is_running = True
        self._thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._thread.start()
        print("Presence detector started")
    
    def stop(self):
        """Stop the presence detection."""
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=5)
        
        if self.camera:
            self.camera.release()
            self.camera = None
        
        print("Presence detector stopped")
    
    def add_callback(self, callback: Callable[[bool], None]):
        """
        Add a callback function to be called when presence changes.
        
        Args:
            callback: Function that takes a boolean (True if person present)
        """
        self._callbacks.append(callback)
    
    def _notify_callbacks(self, present: bool):
        """Notify all registered callbacks of presence change."""
        for callback in self._callbacks:
            try:
                callback(present)
            except Exception as e:
                print(f"Error in presence callback: {e}")
    
    def _detection_loop(self):
        """Main detection loop running in background thread."""
        # Open camera
        self.camera = cv2.VideoCapture(0)
        
        if not self.camera.isOpened():
            print("Error: Could not open camera")
            self.is_running = False
            return
        
        # Set camera properties for faster processing
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        previous_state = self.person_present
        
        print(f"Starting presence detection in '{self.detection_mode}' mode")
        
        while self.is_running:
            try:
                start_time = time.time()
                
                ret, frame = self.camera.read()
                
                if not ret:
                    print("Error: Could not read frame from camera")
                    time.sleep(self.check_interval)
                    continue
                
                # Convert to RGB for MediaPipe
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # Detect based on mode
                person_detected = False
                detection_type = ""
                
                # Check for faces
                if self.face_detection:
                    face_results = self.face_detection.process(rgb_frame)
                    if face_results.detections:
                        person_detected = True
                        detection_type = "face"
                
                # Check for body/pose (if not already detected or in "both" mode)
                if self.pose_detection and (not person_detected or self.detection_mode == "both"):
                    pose_results = self.pose_detection.process(rgb_frame)
                    
                    # Check if pose landmarks were detected with sufficient visibility
                    if pose_results.pose_landmarks:
                        # Check key body landmarks for visibility
                        # Using shoulders, hips, or torso landmarks
                        key_landmarks = [
                            pose_results.pose_landmarks.landmark[self.mp_pose.PoseLandmark.LEFT_SHOULDER],
                            pose_results.pose_landmarks.landmark[self.mp_pose.PoseLandmark.RIGHT_SHOULDER],
                            pose_results.pose_landmarks.landmark[self.mp_pose.PoseLandmark.LEFT_HIP],
                            pose_results.pose_landmarks.landmark[self.mp_pose.PoseLandmark.RIGHT_HIP],
                        ]
                        
                        # If at least 2 key landmarks are visible with good confidence
                        visible_count = sum(1 for lm in key_landmarks if lm.visibility > self.detection_confidence)
                        
                        if visible_count >= 2:
                            person_detected = True
                            detection_type = "pose" if detection_type == "" else "face+pose"
                
                # Update presence status
                if person_detected:
                    self.person_present = True
                    self.last_detection_time = time.time()
                else:
                    self.person_present = False
                
                # Notify if state changed
                if self.person_present != previous_state:
                    status_msg = f"Presence changed: {'Person detected' if self.person_present else 'No person detected'}"
                    if self.person_present and detection_type:
                        status_msg += f" ({detection_type})"
                    print(status_msg)
                    self._notify_callbacks(self.person_present)
                    previous_state = self.person_present
                
                # Sleep for remaining interval time
                elapsed = time.time() - start_time
                sleep_time = max(0, self.check_interval - elapsed)
                time.sleep(sleep_time)
                
            except Exception as e:
                print(f"Error in detection loop: {e}")
                time.sleep(self.check_interval)
        
        # Cleanup
        if self.camera:
            self.camera.release()
    
    def get_presence_status(self) -> bool:
        """Get current presence status."""
        return self.person_present
    
    def get_time_since_last_detection(self) -> float:
        """Get time in seconds since last detection."""
        if self.last_detection_time == 0:
            return float('inf')
        return time.time() - self.last_detection_time
