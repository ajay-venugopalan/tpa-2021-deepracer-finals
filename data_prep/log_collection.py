import yaml
import json
import pandas as pd
from os import path

def parse_message( message_text ):

    hdr = "episode,step,x-coordinate,y-coordinate,heading,steering_angle,speed,action_taken,reward,job_completed,all_wheels_on_track,progress, closest_waypoint_index,track_length,time,state"
    message_text = message_text.replace('SIM_TRACE_LOG:','')

    headers = hdr.split(",")
    data = message_text.replace('SIM_TRACE_LOG:','').split(",")
    
    data_dict = {}
    for i in range(len(data)):
        data_dict[headers[i]] = data[i]

    return data_dict

def evaluate_and_sort( raw_log_data ):

    # Data conditioning
    df = pd.DataFrame(raw_log_data)
    df = df[["team","car_no","episode","step","time","progress","state","x-coordinate","y-coordinate"]]
    for float_var in ["time","progress","x-coordinate","y-coordinate"]:
        df[float_var] = df[float_var].astype("float")
    for int_var in ["episode","step"]:
        df[int_var] = df[int_var].astype("int")
    df.sort_values(by=["team","episode","step","time"], inplace=True)
    df = df.reset_index(drop=True)

    df_min_time = df[["team","episode","time"]].groupby(["team","episode"]).min()
    df_min_time = df_min_time.rename(columns={"time":"start_time"})
    df_max_time = df[["team","episode","time"]].groupby(["team","episode"]).max()
    df_max_time = df_max_time.rename(columns={"time":"end_time"})

    # Determine the end results of each episode, sort by best to worst performance (progress and steps)
    df_end_state = df[ df["state"] != "in_progress"  ]
    df_end_state = df_end_state[["team","episode","progress","state","step"]] 

    df_end_state = df_end_state.merge(df_min_time, on=["team","episode"])
    df_end_state = df_end_state.merge(df_max_time, on=["team","episode"])
    df_end_state["lap_time"] = df_end_state["end_time"] - df_end_state["start_time"] 
    df_end_state = df_end_state.sort_values(by=["team","progress","lap_time"], ascending=[True,False,True]).reset_index(drop=True)
    df_end_state["race_number"] = df_end_state.index + 1
    df_end_state = df_end_state.rename(columns={"progress": "lap_progress", 
                                            "state": "lap_end_state", "step": "lap_step_count"})
   

    # Merge in the lap summary back to data
    df=df_end_state.merge(df, how="inner", on=["team","episode"])
    df["time"] = df["time"] - df["start_time"]
    df=df[["race_number","team","car_no","lap_progress", "lap_end_state", "lap_time", "lap_step_count",
           "episode","step","time","progress","state","x-coordinate","y-coordinate"]]
    
    return df

def process_team_log_file( team ):

    team_name = team["team"]
    log_file_name = path.join("cloudwatch_logs",team["logfile"])

    print(f"Processing {team_name} log file {log_file_name}")

    dr_trace = []
    with open(log_file_name,"r" ) as logfile:
        for msg in json.load(logfile)["events"]:
            if msg["message"].startswith("SIM_TRACE_LOG:"):
                payload = parse_message(msg["message"])
                payload["team"] = team_name
                payload["car_no"] = str(int(team["car"])).zfill(2)
                dr_trace.append(payload)

    return dr_trace   

def process_teams( yaml_file = "log_file_map.yml"):

    with open(yaml_file,"r") as yfp:
        file_to_team_map = yaml.load(yfp, Loader=yaml.FullLoader)
       
    full_data_set = None

    for team in file_to_team_map:
        raw_log_data = process_team_log_file( team )
        team_data = evaluate_and_sort(raw_log_data)

        if full_data_set is None:
            full_data_set = team_data
        else:
            full_data_set = pd.concat([full_data_set,team_data])

    full_data_set.sort_values(by=["race_number","team","step"], inplace=True)
    generate_races(full_data_set)
    generate_leaderboards(full_data_set)
    #full_data_set.to_csv("race_data_out.csv", index=False)

def generate_leaderboards( race_data ):

    summary = race_data[["race_number","team","car_no","lap_end_state","lap_progress","lap_time"]].copy().drop_duplicates()
    race_list = summary.race_number.unique()
    for race_no in race_list:
        print(f"Generate Race Result {race_no}")
        one_race_lb = summary[summary.race_number == race_no].copy()
        one_race_lb.sort_values(by=["lap_progress","lap_time"], ascending=[False,True], inplace=True)
        one_race_lb= one_race_lb.reset_index(drop=True)
        one_race_lb.index = one_race_lb.index + 1
        one_race_lb.index.name = "Place"
        one_race_lb.drop(["race_number"], axis=1, inplace=True)
        one_race_lb.to_html(path.join("race_data",f'race_{race_no}_results.html'))


def generate_races( race_data ):

    race_list = race_data.race_number.unique()

    for race_no in race_list:
        print(f"Generate Race Data {race_no}")
        one_race_data = race_data[race_data.race_number == race_no]
        race_teams = one_race_data.team.unique()
        race_json = []
        for team in race_teams:
            one_race_team_data = one_race_data[one_race_data.team == team].reset_index(drop=True)
            race_team_json = { "team": team,
                               "car_no" : one_race_team_data.loc[0, 'car_no'],
                               "lap_end_state" : one_race_team_data.loc[0, 'lap_end_state'],
                               "lap_progress" : one_race_team_data.loc[0, 'lap_progress'],
                               "lap_time" : one_race_team_data.loc[0, 'lap_time'],
                               "plot" : []
                             }
            for i in range(one_race_team_data.step.count()):
                race_team_json["plot"].append( ( one_race_team_data.loc[i, 'x-coordinate'],
                                              one_race_team_data.loc[i, 'y-coordinate']) )
                race_json.append(race_team_json)

        with open(path.join("race_data",f'race_{race_no}_data.json'), 'w') as fp:
            json.dump(race_json, fp, sort_keys=False, indent=2)
            

if __name__ == "__main__":
    process_teams("log_file_map.yml")