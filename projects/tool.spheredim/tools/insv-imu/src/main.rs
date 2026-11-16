use insta360_rs::{
    container::VideoPtsMapType,
    motion::{decode_motion_record, profile::X5MotionProfile},
    telemetry::decode_camera_exposure_record,
    timing::ExposureTimeline,
    AttitudeTrack, FusionOptions, InsvReader,
};
use std::{
    env,
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    process::Command,
    time::Duration,
};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let a: Vec<String> = env::args().collect();
    if a.len() != 3 {
        return Err("usage: imu INPUT OUTPUT_DIR".into());
    }
    let mut reader = InsvReader::new(File::open(&a[1])?)?;
    let inspection = reader.inspect()?;
    let m = &inspection.metadata;
    let record = |id: u8| {
        inspection
            .records
            .iter()
            .find(|r| r.id == id)
            .ok_or_else(|| format!("missing record {id}"))
    };
    let gyro = reader.read_record_payload(record(3)?, 512 * 1024 * 1024)?;
    let exposure = reader.read_record_payload(record(4)?, 512 * 1024 * 1024)?;
    let origin = i64::from_le_bytes(gyro.get(..8).ok_or("truncated gyro record")?.try_into()?);
    let first = m
        .first_frame_timestamp
        .ok_or("missing first frame camera timestamp")?;
    let exposures = decode_camera_exposure_record(&exposure, m)?;
    let result = Command::new("ffprobe")
        .args([
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_packets",
            "-show_entries",
            "packet=pts_time",
            "-of",
            "csv=p=0",
            &a[1],
        ])
        .output()?;
    if !result.status.success() {
        return Err("ffprobe failed".into());
    }
    let pts: Vec<i64> = String::from_utf8(result.stdout)?
        .lines()
        .filter(|s| !s.trim().is_empty())
        .map(|s| {
            s.trim()
                .trim_end_matches(',')
                .parse::<f64>()
                .map(|v| (v * 1_000_000.).round() as i64)
        })
        .collect::<Result<_, _>>()?;
    if pts.is_empty() || pts.windows(2).any(|w| w[1] <= w[0]) {
        return Err("video packet PTS must be nonempty and strictly increasing; reordered frames are unsupported".into());
    }
    let timeline = ExposureTimeline::new(&exposures, first, &pts)?;
    let mut n = m.clone();
    n.first_frame_timestamp = Some(origin);
    n.gyro_timestamp_adjust_ms = Some(0.);
    n.video_pts_map_type = Some(VideoPtsMapType::DecoderWithFirstFrameTimestamp);
    let mut samples = decode_motion_record(&gyro, &n)?;
    X5MotionProfile::from_metadata(m)?.normalize_samples(&mut samples)?;
    let first_capture = timeline.timestamp_micros_at_pts(pts[0])?
        + m.gyro_timestamp_adjust_ms.unwrap_or(0.) * 1000.
        - timeline.shutter_speed_at_pts(pts[0])?.as_secs_f64() * 500_000.;
    let mut opts = FusionOptions::default();
    opts.initialization_window =
        Duration::from_secs_f64(((first_capture - origin as f64) / 1e6).min(2.));
    opts.max_angular_speed_rad_s = m
        .imu_range
        .ok_or("missing IMU range")?
        .gyroscope_degrees_per_second
        .to_radians()
        * 3.0_f64.sqrt();
    let track = AttitudeTrack::new(&samples, opts)?;
    std::fs::create_dir_all(&a[2])?;
    let mut sensor = BufWriter::new(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(format!("{}/imu_fused.csv", a[2]))?,
    );
    writeln!(
        sensor,
        "camera_us,ax_g,ay_g,az_g,gx_rad_s,gy_rad_s,gz_rad_s,q_w,q_x,q_y,q_z"
    )?;
    for sample in &samples {
        let q = track.pose_at(sample.timestamp)?;
        writeln!(
            sensor,
            "{},{},{},{},{},{},{},{},{},{},{}",
            origin + sample.timestamp.as_micros() as i64,
            sample.acceleration[0],
            sample.acceleration[1],
            sample.acceleration[2],
            sample.angular_velocity[0],
            sample.angular_velocity[1],
            sample.angular_velocity[2],
            q.w,
            q.x,
            q.y,
            q.z
        )?;
    }
    let mut frames = BufWriter::new(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(format!("{}/orientation_frames_fused.csv", a[2]))?,
    );
    writeln!(
        frames,
        "frame,video_pts_s,camera_exposure_center_us,q_w,q_x,q_y,q_z,heading_rad"
    )?;
    for (idx, p) in pts.iter().enumerate() {
        let capture = timeline.timestamp_micros_at_pts(*p)?
            + m.gyro_timestamp_adjust_ms.unwrap_or(0.) * 1000.
            - timeline.shutter_speed_at_pts(*p)?.as_secs_f64() * 500_000.;
        let t = Duration::from_secs_f64((capture - origin as f64) / 1e6);
        let q = track.pose_at(t)?;
        writeln!(
            frames,
            "{},{},{},{},{},{},{},{}",
            idx,
            *p as f64 / 1e6,
            capture,
            q.w,
            q.x,
            q.y,
            q.z,
            track.heading_at(t)?
        )?;
    }
    println!(
        "imu_samples={} frames={} initial_window_s={} diagnostics={:?}",
        samples.len(),
        pts.len(),
        opts.initialization_window.as_secs_f64(),
        track.diagnostics()
    );
    Ok(())
}
