#!/usr/bin/python

import os

import rospkg
import rospy
import rosbag

import math
import numpy as np

from gnss_ins_sim.sim import imu_model
from gnss_ins_sim.sim import ins_sim

from std_msgs.msg import String
from std_msgs.msg import Float64
from sensor_msgs.msg import Imu
from nav_msgs.msg import Odometry
from gnss_ins_sim.geoparams import geoparams


def get_gnss_ins_sim(motion_def_file, fs_imu, fs_gps):
    '''
    Generate simulated GNSS/IMU data using specified trajectory.
    '''
    # set IMU model:
    D2R = math.pi/180.0
    # imu_err = 'low-accuracy'
    imu_err = {
        # 1. gyro:
        # a. random noise:
        # gyro angle random walk, deg/rt-hr
        'gyro_arw': np.array([0.75, 0.75, 0.75]),
        # gyro bias instability, deg/hr
        'gyro_b_stability': np.array([10.0, 10.0, 10.0]),
        # gyro bias isntability correlation time, sec
        'gyro_b_corr': np.array([100.0, 100.0, 100.0]),
        # b. deterministic error:
        'gyro_b': np.array([0.0, 0.0, 0.0]),
        'gyro_k': np.array([1.0, 1.0, 1.0]),
        'gyro_s': np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        # 2. accel:
        # a. random noise:
        # accel velocity random walk, m/s/rt-hr
        'accel_vrw': np.array([0.05, 0.05, 0.05]),
        # accel bias instability, m/s2
        'accel_b_stability': np.array([2.0e-4, 2.0e-4, 2.0e-4]),
        # accel bias isntability correlation time, sec
        'accel_b_corr': np.array([100.0, 100.0, 100.0]),
        # b. deterministic error:
        'accel_b': np.array([0.0e-3, 0.0e-3, 0.0e-3]),
        'accel_k': np.array([1.0, 1.0, 1.0]),
        'accel_s': np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        # 3. mag:
        'mag_si': np.eye(3) + np.random.randn(3, 3)*0.0, 
        'mag_hi': np.array([10.0, 10.0, 10.0])*0.0,
        'mag_std': np.array([0.1, 0.1, 0.1])
    }
    # generate GPS and magnetometer data:
    imu = imu_model.IMU(accuracy=imu_err, axis=9, gps=True)

    # init simulation:
    sim = ins_sim.Sim(
        [fs_imu, fs_gps, fs_imu],
        motion_def_file,
        ref_frame=1,
        imu=imu,
        mode=None,
        env=None,
        algorithm=None
    )
    
    # run:
    sim.run(1)

    # get simulated data:
    rospy.logwarn(
        "Simulated data size {}".format(
            len(sim.dmgr.get_data_all('gyro').data[0])
        )
    )

    # imu measurements:
    step_size = 1.0 / fs_imu
    for i, (gyro, accel, ref_pos, ref_att_quat) in enumerate(
        zip(
            # a. gyro
            sim.dmgr.get_data_all('gyro').data[0], 
            # b. accel
            sim.dmgr.get_data_all('accel').data[0],
            # c. ref pos
            sim.dmgr.get_data_all('ref_pos').data,
            # d. att quat
            sim.dmgr.get_data_all('ref_att_quat').data
        )
    ):
        yield {
            'stamp': i * step_size,
            'data': {
                # a. gyro:
                'gyro_x': gyro[0],
                'gyro_y': gyro[1],
                'gyro_z': gyro[2],
                # b. accel:
                'accel_x': accel[0],
                'accel_y': accel[1],
                'accel_z': accel[2],
                # c. ref pos
                'ref_pos_x': ref_pos[0],
                'ref_pos_y': ref_pos[1],
                'ref_pos_z': ref_pos[2],
                # d. ref_att_quat
                'q0': ref_att_quat[0],
                'q1': ref_att_quat[1],
                'q2': ref_att_quat[2],
                'q3': ref_att_quat[3]
            }
        }


def gnss_ins_sim_recorder():
    """
    Record simulated GNSS/IMU data as ROS bag
    """
    # ensure gnss_ins_sim_node is unique:
    rospy.init_node('gnss_ins_sim_recorder_node')

    # parse params:
    motion_def_name = rospy.get_param('/gnss_ins_sim_recorder_node/motion_file')
    sample_freq_imu = rospy.get_param('/gnss_ins_sim_recorder_node/sample_frequency/imu')
    sample_freq_gps = rospy.get_param('/gnss_ins_sim_recorder_node/sample_frequency/gps')
    topic_name_imu = rospy.get_param('/gnss_ins_sim_recorder_node/topic_name_imu')
    topic_name_pos = rospy.get_param('/gnss_ins_sim_recorder_node/topic_name_pos')
    rosbag_output_path = rospy.get_param('/gnss_ins_sim_recorder_node/output_path')
    rosbag_output_name = rospy.get_param('/gnss_ins_sim_recorder_node/output_name')

    # generate simulated data:
    motion_def_path = os.path.join(
        rospkg.RosPack().get_path('gnss_ins_sim'), 'config', 'motion_def', motion_def_name
    )
    imu_simulator = get_gnss_ins_sim(
        # motion def file:
        motion_def_path,
        # gyro-accel/gyro-accel-mag sample rate:
        sample_freq_imu,
        # GPS sample rate:
        sample_freq_gps
    )

    with rosbag.Bag(
        os.path.join(rosbag_output_path, rosbag_output_name), 'w'
    ) as bag:
        # get timestamp base:
        timestamp_start = rospy.Time.now()

        idx = 0

        for measurement in imu_simulator:
            # set pose
            if idx == 0:
                x_ori = measurement['data']['ref_pos_x']
                y_ori = measurement['data']['ref_pos_y']
                z_ori = measurement['data']['ref_pos_z']
                idx = 1


            msg_pos = Odometry()
            msg_pos.header.stamp = timestamp_start + rospy.Duration.from_sec(measurement['stamp'])
            msg_pos.header.frame_id = "inertial"
            msg_pos.child_frame_id = "inertial"
            msg_pos.pose.pose.position.x = measurement['data']['ref_pos_x'] - x_ori
            msg_pos.pose.pose.position.y = measurement['data']['ref_pos_y'] - y_ori
            msg_pos.pose.pose.position.z = measurement['data']['ref_pos_z'] - z_ori
            msg_pos.pose.pose.orientation.x = measurement['data']['q0']
            msg_pos.pose.pose.orientation.y = measurement['data']['q1']
            msg_pos.pose.pose.orientation.z = measurement['data']['q2']
            msg_pos.pose.pose.orientation.w = measurement['data']['q3']

            # set g
            # calculate g
            rpx = measurement['data']['ref_pos_x']- x_ori
            rpy = measurement['data']['ref_pos_y']- y_ori
            rpz = measurement['data']['ref_pos_z']- z_ori
            earth_para = geoparams.geo_param([rpx, rpy, rpz])
            g = earth_para[2]

            # init:
            msg = Imu()
            # a. set header:
            msg.header.frame_id = 'ENU'
            msg.header.stamp = timestamp_start + rospy.Duration.from_sec(measurement['stamp'])
            # b. set orientation estimation:
            msg.orientation.x = measurement['data']['q0']
            msg.orientation.y = measurement['data']['q1']
            msg.orientation.z = measurement['data']['q2']
            msg.orientation.w = measurement['data']['q3']
            # c. gyro:
            msg.angular_velocity.x = measurement['data']['gyro_x']
            msg.angular_velocity.y = measurement['data']['gyro_y']
            msg.angular_velocity.z = measurement['data']['gyro_z']
            msg.linear_acceleration.x = measurement['data']['accel_x']
            msg.linear_acceleration.y = measurement['data']['accel_y']
            msg.linear_acceleration.z = measurement['data']['accel_z'] + g

            # write:
            bag.write(topic_name_imu, msg, msg.header.stamp)
            bag.write(topic_name_pos, msg_pos, msg_pos.header.stamp)

if __name__ == '__main__':
    try:
        gnss_ins_sim_recorder()
    except rospy.ROSInterruptException:
        pass