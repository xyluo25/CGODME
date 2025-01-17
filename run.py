import warnings
import tensorflow as tf
import pandas as pd
import numpy as np
import math
from data import data_generation
from calibration import calculateCoreVars, optimizeSupply
import argparse
import logging
warnings.filterwarnings('ignore') # ignore warning messages
logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.DEBUG) # configuration of logging messages


def admm_optimization(od_volume: tf.Tensor,
                      spare_od_path_inc: tf.SparseTensor,
                      path_link_inc: tf.Tensor,
                      path_link_inc_n: tf.Tensor,
                      path_flow: tf.Tensor,
                      bpr_params: dict,
                      lagrangian_params: dict,
                      lambda_positive: tf.Tensor,
                      training_steps: int,
                      link_data: dict,
                      init_path_flows: tf.Tensor) -> None:

    """
    Perform ADMM optimization for path flows.

    Parameters:
    - od_volume (tf.Tensor): Origin-Destination (OD) volume matrix.
    - spare_od_path_inc (tf.SparseTensor): Sparse OD path incidence matrix.
    - path_link_inc (tf.Tensor): Path-link incidence matrix.
    - path_link_inc_n (tf.Tensor): Path-link incidence matrix with one pair.
    - path_flow (tf.Tensor): Initial path flows.
    - bpr_params (dict): Parameters for the BPR (Bureau of Public Roads) function.
    - lagrangian_params (dict): Parameters for the Lagrangian multiplier update.
    - lambda_positive (tf.Tensor): Lagrangian multipliers for positive path flows.
    - training_steps (int): Number of ADMM training steps.
    - obs_link_volumes (dict): total link volumes; car/truck link volumes.

    Returns:
    None
    """

    # relative_gap = []
    # for i in range(training_steps):
    #     logging.info("Training Step %d: Finding optimal path flows", i+1)
    #     path_cost_, path_flow_n_, path_cost_n_, path_flow_all_, link_flow_, link_cost_ = \
    #         calculateCoreVars(path_flow,
    #                           od_volume,
    #                           spare_od_path_inc,
    #                           path_link_inc,
    #                           path_link_inc_n,
    #                           bpr_params,
    #                           )
    #
    #     logging.info("Computing minimum costs")
    #     ue_cost0 = []
    #
    #     for i in range(len(path_cost_n_)):
    #         od_pair = tf.sparse.to_dense(tf.sparse.slice(spare_od_path_inc, [i, 0], [1, len(path_cost_)]))
    #         min_cost = tf.reduce_min(
    #             tf.multiply(tf.where(od_pair == 0, 1.0, 0) * 1e5 + od_pair, tf.reshape(path_cost_, (-1))))
    #         ue_cost0.append(min_cost)
    #     ue_cost0 = tf.reshape(tf.stack(ue_cost0), (tf.stack(ue_cost0).shape[0], 1))
    #     ue_cost = tf.reshape(tf.reduce_min(tf.concat([ue_cost0, path_cost_n_], axis=1), axis=1), (-1, 1))
    #
    #     # calculate the relative gap
    #     comp_gap = tf.reduce_sum(tf.reshape(path_flow, (path_flow.shape[0], 1)) *
    #                              (path_cost_ - tf.transpose(tf.sparse.sparse_dense_matmul(tf.transpose(ue_cost),
    #                                                                                       spare_od_path_inc)))) / \
    #                tf.reduce_sum(tf.reshape(path_flow, (path_flow.shape[0], 1)) * path_cost_) \
    #                + tf.reduce_sum(path_flow_n_ * (path_cost_n_ - ue_cost)) / tf.reduce_sum(path_flow_n_ * path_cost_n_)
    #
    #     relative_gap.append(comp_gap.numpy())
    #     logging.info("Relative gap: %s", comp_gap.numpy())
    logging.info("Finding Optimal Path Flows...")
    path_flow, losses = optimizeSupply(path_flow,
                               lambda_positive,
                               bpr_params,
                               lagrangian_params,
                               od_volume,
                               spare_od_path_inc,
                               path_link_inc,
                               path_link_inc_n,
                               link_data,
                               init_path_flows,
                               )

    estimated_link_volumes = tf.squeeze(calculateCoreVars(path_flow, od_volume, spare_od_path_inc,
                                               path_link_inc, path_link_inc_n, bpr_params))

    evaluation(losses, path_flow, estimated_link_volumes, link_data)

    # logging.info("Updating the Lagrangian multipliers")
    # lambda_positive += lagrangian_params["rho_factor"] * \
    #                        lagrangian_params["rho_factor"] * (tf.nn.relu(-path_flow_all_))
    logging.info("Complete!")

def rmse(estimated, observation):
    squared_diff = (estimated - observation) ** 2
    mean_squared_diff = np.mean(squared_diff)
    rmse_value = np.sqrt(mean_squared_diff)
    return rmse_value

def evaluation(losses, optimal_path_flows, estimated_link_volumes, link_data):
    logging.info("Saving the loss result ...")
    get_df_losses = pd.DataFrame(losses, columns=["losses"])
    get_df_losses.index.name = "epoch"
    get_df_losses.to_csv("loss_results.csv")

    logging.info("Saving the estimated path flows ...")
    pd.DataFrame(optimal_path_flows.numpy(), columns=["Path_Flows"]).to_csv("estimated_path_flows.csv", index=False)

    # RMSE for a goodness of fit
    # NOTE: 0.9 means 90 percent of link volumes is car
    # rmse_tot_link_volumes = rmse(estimated_link_volumes, target_link_volumes["total_link_volume"])
    # logging.info(f"RMSE - Total Link Volumes: {rmse_tot_link_volumes}")
    rmse_car_link_volumes = rmse(estimated_link_volumes * 0.9, link_data["car_link_volume"])
    rmse_truck_link_volumes = rmse(estimated_link_volumes * 0.1, link_data["truck_link_volume"])
    rmse_car_vmt = rmse(estimated_link_volumes * 0.9 * link_data["distance_miles"],
                        link_data["car_link_volume"] * 0.9 * link_data["distance_miles"])
    rmse_truck_vmt = rmse(estimated_link_volumes * 0.1 * link_data["distance_miles"],
                        link_data["truck_link_volume"] * 0.1 * link_data["distance_miles"])
    logging.info(f"RMSE - Car Link Volumes: {rmse_car_link_volumes}")
    logging.info(f"RMSE - Truck Link Volumes: {rmse_truck_link_volumes}")
    logging.info(f"RMSE - Car VMT: {rmse_car_vmt}")
    logging.info(f"RMSE - Truck VMT: {rmse_truck_vmt}")

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('--data_dir',
                        type=str,
                        default="./data/Sioux_Falls/",
                        help="Directory containing data files")

    parser.add_argument('--training_steps',
                        type=int,
                        default=5,
                        help="Number of ADMM training steps")
    args = parser.parse_args()

    load_data = data_generation(args.data_dir)
    od_volume, spare_od_path_inc, path_link_inc, path_link_inc_n, _, = load_data.reformed_incidence_mat()
    path_flow = load_data.get_init_path_values(init_given=False)
    init_path_flow = path_flow
    bpr_params = load_data.get_bpr_params()
    loaded_target_count = load_data.link_df["volume"]
    total_link_volume = np.array(loaded_target_count, dtype='f')

    link_data = {}
    link_data["total_link_volume"] = np.array(load_data.link_df["volume"], dtype="f")
    link_data["car_link_volume"] = np.array(load_data.link_df["car_vol"], dtype="f")
    link_data["truck_link_volume"] = np.array(load_data.link_df["truck_vol"], dtype="f")
    link_data["distance_miles"] = np.array(load_data.link_df["distance_mile"], dtype="f")

    lagrangian_params, lambda_positive = load_data.get_lagrangian_params(path_link_inc_n, path_link_inc)
    admm_optimization(od_volume=od_volume,
                      spare_od_path_inc=spare_od_path_inc,
                      path_link_inc=path_link_inc,
                      path_link_inc_n=path_link_inc_n,
                      path_flow=path_flow,
                      bpr_params=bpr_params,
                      lagrangian_params=lagrangian_params,
                      lambda_positive=lambda_positive,
                      training_steps=args.training_steps,
                      link_data=link_data,
                      init_path_flows=init_path_flow)
