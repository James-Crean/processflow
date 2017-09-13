import logging
import subprocess
import sys
import traceback
import re
import os
import threading
import socket
from pprint import pformat
from shutil import copytree, rmtree
from subprocess import Popen, PIPE
from time import sleep
from time import strftime
from datetime import datetime
from uuid import uuid4

from globus_cli.commands.login import do_link_login_flow, check_logged_in
from globus_cli.commands.ls import _get_ls_res as get_ls
from globus_cli.services.transfer import get_client
from globus_sdk import TransferData

from YearSet import SetStatus
from YearSet import YearSet
from jobs.JobStatus import JobStatus
from mailer import Mailer
from string import Formatter

def transfer_directory(**kwargs):
    """
    Transfer all the contents from source_endpoint:src_path to destination_endpoint:dst_path
    
    parameters:
        source_endpoint (str) the globus UUID for the source files
        destination_endpoint (str) the globus UUID for the destination
        src_path (str) the path to the source directory to copy
        dst_path (str) the path on the destination directory
    """
    source_endpoint = kwargs['source_endpoint']
    destination_endpoint = kwargs['destination_endpoint']
    src_path = kwargs['src_path']
    dst_path = kwargs['dst_path']
    event_list = kwargs['event_list']

    client = get_client()
    transfer = TransferData(
        client,
        source_endpoint,
        destination_endpoint,
        sync_level='checksum')
    transfer.add_item(
        source_path=src_path,
        destination_path=dst_path,
        recursive=True)
    try:
        result = client.submit_transfer(transfer)
        task_id = result['task_id']
    except:
        return False
    
    directory_name = src_path.split(os.sep)[-1]
    msg = '{dir} transfer starting'.format(dir=directory_name)
    event_list.push(message=msg)
    while True:
        status = client.get_task(task_id).get('status')
        if status == 'SUCCEEDED':
            msg = '{dir} transfer complete'.format(dir=directory_name)
            return True
        elif status == 'FAILED':
            msg = '{dir} transfer FAILED'.format(dir=directory_name)
            return False
        else:
            event_list.push(message=msg)
            sleep(5)
    

def check_globus(**kwargs):
    """
    Check that the globus endpoints are not only active but will return information
    about the paths we're interested in.

    Im assuming that the endpoints have already been activated
    """
    try:
        endpoints = [{
            'type': 'source',
            'id': kwargs['source_endpoint'],
            'path': kwargs['source_path']
        }, {
            'type': 'destination',
            'id': kwargs['destination_endpoint'],
            'path': kwargs['destination_path']
        }]
    except Exception as e:
        print_debug(e)

    client = get_client()
    try:
        for endpoint in endpoints:
            res = get_ls(
                client,
                endpoint['path'],
                endpoint['id'],
                False, 0, False)
    except:
        return False, endpoint
    else:
        return True, None

def check_config_white_space(filepath):
    line_index = 0
    found = False
    with open(filepath, 'r') as infile:
        for line in infile.readlines():
            line_index += 1
            index = line.find('=')
            if index == -1:
                found = False
                continue
            if line[index + 1] != ' ':
                found = True
                break
    if found:
        return line_index
    else:
        return 0

def strfdelta(tdelta, fmt):
    f = Formatter()
    d = {}
    l = {'D': 86400, 'H': 3600, 'M': 60, 'S': 1}
    k = map( lambda x: x[1], list(f.parse(fmt)))
    rem = int(tdelta.total_seconds())

    for i in ('D', 'H', 'M', 'S'):
        if i in k and i in l.keys():
            d[i], rem = divmod(rem, l[i])

    return f.format(fmt, **d)

def year_from_filename(filename):
    pattern = r'\.\d\d\d\d-'
    index = re.search(pattern, filename)
    if index:
        year = int(filename[index.start() + 1: index.start() + 5])
        return year
    else:
        return 0

def setup_globus(endpoints, no_ui=False, **kwargs):
    """
    Check globus login status and login as nessisary, then
    iterate over a list of endpoints and activate them all
    
    Parameters:
       endpoints: list of strings containing globus endpoint UUIDs
       no_ui: a boolean flag, true if running without the UI

       kwargs:
        event_list: the display event list to push user notifications
        display_event: the thread event for the ui to turn off the ui for grabbing input for globus
        src: an email address to send notifications to if running in no_ui mode
        dst: a destination email address
    return:
       True if successful, False otherwise
    """
    message_sent = False
    display_event = kwargs.get('display_event')
    
    if no_ui:
        mailer = Mailer(
            src=kwargs['src'],
            dst=kwargs['dst'])

    # First go through the globus login process
    while not check_logged_in():
        # if in no_ui mode, send an email to the user with a link to log in
        if no_ui:
            if not kwargs.get('src') or not kwargs.get('dst'):
                logging.error('No source or destination given to setup_globus')
                return False
            if kwargs.get('event_list'):
                line = 'Waiting on user to log into globus, email sent to {addr}'.format(
                    addr=kwargs['src'])
                kwargs['event_list'].push(message=line)
            if not message_sent:
                status = 'Globus login needed'
                message = 'Your automated post processing job requires you log into globus. Please ssh into {host} activate the environment and run {cmd}\n\n'.format(
                    host=socket.gethostname(),
                    cmd='"globus login"')
                print 'sending login message to {}'.format(kwargs['dst'])
                message_sent = mailer.send(
                    status=status,
                    msg=message)
            sleep(30)
        # if in ui mode, set the display_event and ask for user input
        else:
            if not no_ui:
                display_event.set()
            print '================================================'
            do_link_login_flow()

    if not endpoints:
        if not no_ui:
            display_event.clear()
        return True
    if isinstance(endpoints, str):
        endpoints = [endpoints]
    message_sent = False
    activated = False
    email_msg = ''
    client = get_client()
    while not activated: 
        activated = True
        for endpoint in endpoints:
            msg = 'activating endpoint {}'.format(endpoint)
            logging.info(msg)
            r = client.endpoint_autoactivate(endpoint, if_expires_in=3600)
            logging.info(r['code'])
            if r["code"] == "AutoActivationFailed":
                activated = False
                logging.info('endpoint autoactivation failed, going to manual')
                server_document = client.endpoint_server_list(endpoint)
                for server in server_document['DATA']:
                    hostname = server["hostname"]
                    break
                message = '\n{server} requires manual activation, please open the following URL in a browser to activate the endpoint:\n'.format(
                    server=hostname)
                message += "https://www.globus.org/app/endpoints/{endpoint}/activate \n\n".format(endpoint=endpoint)
                if no_ui:
                    email_msg += message
                else:
                    print message
                    raw_input("Press ENTER after activating the endpoint")
                r = client.endpoint_autoactivate(endpoint, if_expires_in=3600)
                if not r["code"] == "AutoActivationFailed":
                    activated = True

        if not activated:
            if not message_sent:
                print 'sending activation message to {}'.format(kwargs['dst'])
                message_sent = mailer.send(
                    status='Endpoint activation required',
                    msg=email_msg)
            sleep(30)
    if not no_ui:
        display_event.clear()
    return True

def get_climo_output_files(input_path, set_start_year, set_end_year):
    contents = os.listdir(input_path)
    file_list_tmp = [s for s in contents if not os.path.isdir(s)]
    file_list = []
    for climo_file in file_list_tmp:
        start_search = re.search(r'\_\d\d\d\d\d\d', climo_file)
        if not start_search:
            continue
        start_index = start_search.start() + 1
        start_year = int(climo_file[start_index: start_index + 4])
        if not start_year == set_start_year:
            continue
        end_search = re.search(r'\_\d\d\d\d\d\d', climo_file[start_index:])
        if not end_search:
            continue
        end_index = end_search.start() + start_index + 1
        end_year = int(climo_file[end_index: end_index + 4])
        if not end_year == set_end_year:
            continue
        file_list.append(climo_file)
    return file_list

def path_exists(config_items):
    """
    Checks the config for any netCDF file paths and validates that they exist
    """
    for section, options in config_items.items():
        if type(options) != dict:
            continue
        for key, val in options.items():
            if key == 'output_pattern':
                continue
            if not type(val) == str:
                continue
            if val.endswith('.nc') and not os.path.exists(val):
                print "File {key}: {value} does not exist, exiting.".format(key=key, value=val)
                sys.exit(1)

def check_year_sets(job_sets, file_list, sim_start_year, sim_end_year, debug, add_jobs):
    """
    Checks the file_list, and sets the year_set status to ready if all the files are in place,
    otherwise, checks if there is partial data, or zero data
    """
    incomplete_job_sets = [s for s in job_sets
                           if s.status != SetStatus.COMPLETED
                           and s.status != SetStatus.RUNNING
                           and s.status != SetStatus.FAILED]
    for job_set in incomplete_job_sets:

        start_year = job_set.set_start_year
        end_year = job_set.set_end_year

        non_zero_data = False
        data_ready = True
        for i in range(start_year, end_year + 1):
            for j in range(1, 13):
                file_key = '{0}-{1}'.format(i, j)
                status = file_list['ATM'][file_key]

                if status in [SetStatus.NO_DATA, SetStatus.IN_TRANSIT, SetStatus.PARTIAL_DATA]:
                    data_ready = False
                elif status == SetStatus.DATA_READY:
                    non_zero_data = True

        if data_ready:
            job_set.status = SetStatus.DATA_READY
            job_set = add_jobs(job_set)
            continue
        if not data_ready and non_zero_data:
            job_set.status = SetStatus.PARTIAL_DATA
            continue
        if not data_ready and not non_zero_data:
            job_set.status = SetStatus.NO_DATA

    # if debug:
    #     for job_set in job_sets:
    #         start_year = job_set.set_start_year
    #         end_year = job_set.set_end_year
    #         print_message('year_set: {0}: {1}'.format(job_set.set_number, job_set.status), 'ok')
    #         for i in range(start_year, end_year + 1):
    #             for j in range(1, 13):
    #                 file_key = '{0}-{1}'.format(i, j)
    #                 status = file_list[file_key]
    #                 print_message('  {key}: {value}'.format(key=file_key, value=status), 'ok')


def start_ready_job_sets(job_sets, thread_list, debug, event, event_list):
    """
    Iterates over the job sets checking for ready ready jobs, and starts them

    input:
        job_sets: a list of YearSets,
        thread_list: the list of currently running threads,
        debug: boolean debug flag,
        event: an event to pass to any threads we start so we can destroy them if needed
    """
    for job_set in job_sets:
        # if the job state is ready, but hasnt started yet
        if job_set.status  in [SetStatus.DATA_READY, SetStatus.RUNNING]:
            for job in job_set.jobs:
                if job.depends_on:
                    ready = False
                    dep = ''
                    for dependancy in job.depends_on:
                        for djob in job_set.jobs:
                            if djob.get_type() == dependancy:
                                if djob.status == JobStatus.COMPLETED:
                                    ready = True
                                else:
                                    dep = djob
                                break
                    if not ready:
                        msg = '{job} is waiting on {dep}'.format(
                            job=job.get_type(), dep=dep.get_type())
                        logging.info(msg)
                else:
                    # print '{job} is ready'.format(job=job.get_type())
                    ready = True
                if not ready:
                    # print '{job} is not ready'.format(job=job.get_type())
                    continue
                # if the job isnt a climo, and the job that it depends on is done, start it
                if job.status == JobStatus.VALID:
                    while True:
                        try:
                            args = (
                                job,
                                job_set, event,
                                debug, 'slurm',
                                event_list)
                            thread = threading.Thread(
                                target=monitor_job,
                                name='monitor_job for {}'.format(job.get_type()),
                                args=args)
                            thread_list.append(thread)
                            thread.start()
                        except Exception as e:
                            print_debug(e)
                            sleep(1)
                        else:
                            break
                if job.status == JobStatus.INVALID:
                    message = "{type} id: {id} status changed to {status}".format(
                        id=job.job_id,
                        status=job.status,
                        type=job.get_type())
                    logging.error(message)

def cmd_exists(cmd):
    return any(os.access(os.path.join(path, cmd), os.X_OK) for path in os.environ["PATH"].split(os.pathsep))

def handle_completed_job(job, job_set, event_list):
    """
    Perform post execution tasks
    """

    t = threading.current_thread()
    tid = t.ident
    msg = 'Handling completion for thread {} with id {}'.format(
        t.name, tid)
    logging.info(msg)
    # First check that we have the expected output
    if not job.postvalidate():
        message = '{0} completed but doesnt have expected output, setting status to failed'.format(job.get_type())
        event_list.push(
            message=message,
            data=job)
        logging.error(message)
        job.status = JobStatus.FAILED
        job_set.status = SetStatus.FAILED
        return
    else:
        job.status = JobStatus.COMPLETED

    # Finally host the files
    if job.get_type() == 'coupled_diags':
        img_dir = 'coupled_diagnostics_{casename}-obs'.format(
            casename=job.config.get('test_casename'))
        img_src = os.path.join(
            job.config.get('coupled_project_dir'),
            img_dir)
        setup_local_hosting(job, event_list, img_src)
    elif job.get_type() == 'amwg':
        img_dir = '{start:04d}-{end:04d}{casename}-obs'.format(
            start=job.config.get('start_year'),
            end=job.config.get('end_year'),
            casename=job.config.get('test_casename'))
        img_src = os.path.join(
            job.config.get('test_path_diag'),
            '..',
            img_dir)
        setup_local_hosting(job, event_list, img_src)
    elif job.get_type() == 'acme_diags':
        img_src = job.config.get('results_dir')
        setup_local_hosting(job, event_list, img_src)
    
    # Second check if the whole set is done
    job_set_done = True
    for k in job_set.jobs:
        if k.status != JobStatus.COMPLETED:
            job_set_done = False
            break
        if k.status == JobStatus.FAILED:
            job_set.status = SetStatus.FAILED
            return
    if job_set_done:
        job_set.status = SetStatus.COMPLETED
    

def monitor_job(job, job_set, event=None, debug=False, batch_type='slurm', event_list=None):
    """
    Monitor the slurm job, and update the status to 'complete' when it finishes
    This function should only be called from within a thread
    """
    t = threading.current_thread()
    tid = t.ident
    msg = 'THEAD {} STARTING {}'.format(tid, t.name)
    job.start_time = datetime.now()
    job_id = job.execute(batch='slurm')

    # If the job has already been run, handle it like it just finished
    if job_id == 0:
        job.set_status(JobStatus.COMPLETED)
        job.postvalidate()
        if job.status == JobStatus.COMPLETED:
            handle_completed_job(job, job_set, event_list)
            return

    # If the job still needs aditional files to transfer, wait for the transfer to finish
    while job_id == -1:
        job.set_status(JobStatus.WAITING_ON_INPUT)
        if thread_sleep(60, event):
            return
        job_id = job.execute(batch='slurm')
    
    # Prep for submitting the job
    job.set_status(JobStatus.SUBMITTED)
    message = 'Submitted {0} for year_set {1}'.format(
        job.get_type(),
        job_set.set_number)
    event_list.push(
        message=message,
        data=job)
    logging.info(message)

    exit_list = [JobStatus.VALID, JobStatus.SUBMITTED, JobStatus.RUNNING, JobStatus.PENDING]
    none_exit_list = [JobStatus.RUNNING, JobStatus.PENDING, JobStatus.SUBMITTED]
    while True:
        # this check is here in case the loop is stuck and the thread needs to be canceled
        if event and event.is_set():
            return
        if job.status not in exit_list:
            if job.status == JobStatus.INVALID:
                return
            # if the job is done, or there has been an error, exit
            if job.status == JobStatus.FAILED:
                job_set.status = SetStatus.FAILED
                return
            # if the job has completed successfully, handle completion and exit
            if job.status == JobStatus.COMPLETED:
                handle_completed_job(job, job_set, event_list)
                return

        # Job is running
        elif job.status in none_exit_list and job_id != 0:
            cmd = ['scontrol', 'show', 'job', str(job_id)]
            while True:
                try:
                    out = Popen(cmd, stdout=PIPE, stderr=PIPE).communicate()[0]
                except:
                    sleep(1)
                else:
                    break
            # loop through the scontrol output looking for the JobState field
            job_status = None
            for line in out.split('\n'):
                for word in line.split():
                    if 'JobState' in word:
                        index = word.find('=')
                        job_status = word[index + 1:]
                        break
                if job_status:
                    break
            if not job_status:
                sleep(5)
                continue

            status = None
            if job_status == 'RUNNING':
                status = JobStatus.RUNNING
            elif job_status == 'PENDING':
                status = JobStatus.PENDING
            elif job_status == 'FAILED':
                job.end_time = datetime.now()
                status = JobStatus.FAILED
                msg = 'Job {0} has failed'.format(job_id)
                event_list.push(
                    message=msg,
                    data=job)
                return
            elif job_status == 'COMPLETED':
                job.end_time = datetime.now()
                status = JobStatus.COMPLETED
                handle_completed_job(job, job_set, event_list)
                return

            if status and status != job.status:
                job.status = status
                message = "{type}: {id} status changed to {status}".format(
                    id=job.job_id,
                    status=status,
                    type=job.get_type())
                logging.info(message)

            # wait for 10 seconds, or if the kill_thread event has been set, exit
            if thread_sleep(10, event):
                return

def setup_local_hosting(job, event_list, img_src, generate=False):
    """
    Sets up the local directory for hosting diagnostic sets
    """
    msg = 'Setting up local hosting for {}'.format(job.get_type())

    t = threading.current_thread()
    tid = t.ident
    event_list.push(
        message=msg,
        data=job)
    logging.info(msg)
    host_dir = job.config.get('web_dir')
    url = job.config.get('host_url')
    if os.path.exists(host_dir):
        new_id = uuid4().hex[:8]
        host_dir += '_' + new_id
        url += '_' + new_id
        
    if not os.path.exists(img_src):
        msg = '{job} hosting failed, no image source at {path}'.format(
            job=job.get_type(),
            path=img_src)
        logging.error(msg)
        return
    try:
        msg = 'copying images from {src} to {dst}'.format(src=img_src, dst=host_dir)
        logging.info(msg)
        # copytree(src=img_src, dst=host_dir)
        create_symlink_dir(
            src_dir=img_src,
            src_list=os.listdir(img_src),
            dst=host_dir)
    except Exception as e:
        logging.error(format_debug(e))
        msg = 'Error copying {} to host directory'.format(job.get_type())
        event_list.push(
            message=msg,
            data=job)
        return

    temp = host_dir.split(os.sep)
    index = temp.index(os.environ['USER']) + 2
    image_dir = os.sep.join(temp[:index])
    msg = 'Changing permissions on image_dir {}'.format(host_dir)
    logging.info(msg)

    p = Popen(['chmod', '-R', '755', img_src], stdout=PIPE, stderr=PIPE)
    out, err = p.communicate()
    if err:
        event_list.push(
            message=err,
            data=job    )

    if job.get_type() == 'amwg':
        print '--------------------'
        print 'AMWG SETUP AND HOSTED'
        print '--------------------'
    if job.get_type() == 'acme_diags':    
        msg = '{job} hosted at {url}/viewer/index.html'.format(
            url=url,
            job=job.get_type())
    else:
        msg = '{job} hosted at {url}/index.html'.format(
            url=url,
            job=job.get_type())
    event_list.push(
        message=msg,
        data=job)
    logging.info(msg)

def check_for_inplace_data(file_list, file_name_list, config, file_type_map):
    """
    Checks the data cache for any files that might alread   y be in place,
    updates the file_list and job_sets accordingly
    """
    cache_path = config['global']['data_cache_path']
    sim_end_year = int(config['global']['simulation_end_year'])
    if not os.path.exists(cache_path):
        os.makedirs(cache_path)
        return False
    
    patterns = config['global']['patterns']
    input_dirs = [os.path.join(cache_path, key) for key, val in patterns.items()]
    for input_dir in input_dirs:
        file_type = input_dir.split(os.sep)[-1]
        for input_file in os.listdir(input_dir):
            input_file_path = os.path.join(input_dir, input_file)
            file_key = ""
            if file_type_map[file_type][1]:
                file_key = filename_to_file_list_key(filename=input_file)
                index = file_key.find('-')
                year = int(file_key[:index])
                if year > sim_end_year:
                    continue
                if not file_list[file_type][file_key] == SetStatus.IN_TRANSIT:
                    file_list[file_type][file_key] = SetStatus.DATA_READY
                file_name_list[file_type][file_key] = input_file
            else:
                for file_key in file_list[file_type]:
                    if file_key == input_file:
                        if os.path.exists(os.path.join(input_dir, input_file)) and \
                        not file_list[file_type][file_key] == SetStatus.IN_TRANSIT:
                            file_list[file_type][file_key] = SetStatus.DATA_READY
                        file_name_list[file_type][file_key] = input_file

    for key, val in patterns.items():
        for file_key in file_list[key]:
            if file_list[key][file_key] != SetStatus.DATA_READY:
                return False
    return True

def print_debug(e):
    """
    Print an exceptions relavent information
    """
    print '1', e.__doc__
    print '2', sys.exc_info()
    print '3', sys.exc_info()[0]
    print '4', sys.exc_info()[1]
    print '5', traceback.tb_lineno(sys.exc_info()[2])
    _, _, tb = sys.exc_info()
    print '6', traceback.print_tb(tb)

def format_debug(e):
    """
    Return a string of an exceptions relavent information
    """
    _, _, tb = sys.exc_info()
    return '1: {doc} \n2: {exec_info} \n3: {exec_0} \n 4: {exec_1} \n5: {lineno} \n6: {stack}'.format(
        doc=e.__doc__,
        exec_info=sys.exc_info(),
        exec_0=sys.exc_info()[0],
        exec_1=sys.exc_info()[1],
        lineno=traceback.tb_lineno(sys.exc_info()[2]),
        stack=traceback.print_tb(tb))

def write_human_state(event_list, job_sets, state_path='run_state.txt', ui_mode=True):
    """
    Writes out a human readable representation of the current execution state

    Paremeters
        event_list (Event_list): The global list of all events
        job_sets (list: YearSet): The global list of all YearSets
        state_path (str): The path to where to write the run_state
        ui_mode (bool): The UI mode, True if the UI is on, False if the UI is off
    """
    import datetime

    try:
        with open(state_path, 'w') as outfile:
            line = "Execution state as of {0}\n".format(
                datetime.datetime.now().strftime('%d, %b %Y %I:%M'))
            out_str = line
            out_str += 'Running under process {0}\n\n'.format(os.getpid())
            
            for year_set in job_sets:
                line = 'Year_set {num}: {start} - {end}\n'.format(
                    num=year_set.set_number,
                    start=year_set.set_start_year,
                    end=year_set.set_end_year)
                out_str += line
               
                line = 'status: {status}\n'.format(
                    status=year_set.status)
                out_str += line

                for job in year_set.jobs:
                    line = '  >   {type} -- {id}: {status}\n'.format(
                        type=job.get_type(),
                        id=job.job_id,
                        status=job.status)
                    out_str += line
                   
                out_str += '\n'
              
            out_str += '\n'
            for line in event_list.list:
                if 'Transfer' in line.message:
                    continue
                if 'hosted' in line.message:
                    continue
                out_str += line.message + '\n'
               
            # out_str += line.message + '\n'
            for line in event_list.list:
                if 'Transfer' not in line.message:
                    continue
                out_str += line.message + '\n'

            for line in event_list.list:
                if 'hosted' not in line.message:
                    continue
                out_str += line.message + '\n'
            outfile.write(out_str)
            if not ui_mode:
                print '\n'
                print out_str
                print '\n================================================\n'
    except Exception as e:
        logging.error(format_debug(e))
        return

class colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_message(message, status='error'):
    if status == 'error':
        print colors.FAIL + '[-] ' + colors.ENDC + colors.BOLD + str(message) + colors.ENDC
    elif status == 'ok':
        print colors.OKGREEN + '[+] ' + colors.ENDC + str(message)

def render(variables, input_path, output_path, delimiter='%%'):
    """
    Takes an input file path, an output file path, a set of variables, and a delimiter.
    For each instance of that delimiter wrapped around a substring, replaces the
    substring with its matching element from the varialbes dict

    An example variable dict and delimiter would be:

    variables = {
        'test_casename': '20161117.beta0.A_WCYCL1850S.ne30_oEC_ICG.edison',
        'test_native_res': 'ne30',
        'test_archive_dir': '/space2/test_data/ACME_simulations',
        'test_short_term_archive': '0',
        'test_begin_yr_climo': '6',
        'test_end_yr_climo': '10'
    }
    delim = '%%'

    """

    try:
        infile = open(input_path, 'r')
    except IOError as e:
        print 'unable to open input file: {}'.format(input_path)
        print_debug(e)
        return
    try:
        outfile = open(output_path, 'w')
    except IOError as e:
        print 'unable to open output file: {}'.format(output_path)
        print_debug(e)
        return

    for line in infile.readlines():
        rendered_string = ''
        match = re.search(delimiter + '[a-zA-Z_0-9]*' + delimiter, line)
        if match:
            delim_index = [m.start() for m in re.finditer(delimiter, line)]
            if len(delim_index) < 2:
                continue

            template_string = line[delim_index[0] + len(delimiter): delim_index[1]]
            for item in variables:
                if item == template_string:
                    rendered_start = line[:delim_index[0]]
                    rendered_middle = variables[item]
                    rendered_end = line[delim_index[0] + len(delimiter) + len(item) + len(delimiter):]
                    rendered_string += str(rendered_start) + str(rendered_middle) + str(rendered_end)
                else:
                    continue
        else:
            rendered_string = line
        outfile.write(rendered_string)

def is_all_done(job_sets):
    """
    Check if all job_sets are done, and all processing has been completed

    return -1 if still running
    return 0 if a jobset failed
    return 1 if all complete
    """

    # First check for pending jobs
    for job_set in job_sets:
        if job_set.status != SetStatus.COMPLETED and \
           job_set.status != SetStatus.FAILED:
            return -1
    # all job sets are either complete or failed
    for job_set in job_sets:
        if job_set.status != SetStatus.COMPLETED:
            return 0
    return 1

def filename_to_file_list_key(filename):
    """
    Takes a filename and returns the key for the file_list
    """
    pattern = r'\.\d\d\d\d-'
    index = re.search(pattern, filename)
    if index:
        year = int(filename[index.start() + 1: index.start() + 5])
    else:
        return '0-0'
    # the YYYY field is 4 characters long, the month is two
    year_offset = index.start() + 5
    # two characters for the month, and one for the - between year and month
    month_offset = year_offset + 3
    month = int(filename[year_offset + 1: month_offset])
    key = "{year}-{month}".format(year=year, month=month)
    return key

def filename_to_year_set(filename, freq):
    """
    Takes a filename and returns the year_set that the file belongs to

    Parameters
        filename (str or unicode): The name of the file to return the year set for
        freq (int): The length of the year set
    """
    if not isinstance(filename, (unicode, str)):
        print "Filename is a {} not a string".format(type(filename))
        raise
    if not isinstance(freq, int):
        try:
            freq = int(freq)
        except:
            print "Freq is a {} not an int, and can not be converted".format(type(freq))
            raise

    year = year_from_filename(filename)
    if year % freq == 0:
        return int(year / freq)
    else:
        return int(year / freq) + 1


def create_symlink_dir(src_dir, src_list, dst):
    """
    Create a directory, and fill it with symlinks to all the items in src_list
    """
    if not src_list:
        return
    if not os.path.exists(dst):
        os.makedirs(dst)
    for src_file in src_list:
        if not src_file:
            continue
        source = os.path.join(src_dir, src_file)
        destination = os.path.join(dst, src_file)
        if os.path.lexists(destination):
            continue
        try:
            os.symlink(source, destination)
        except Exception as e:
            msg = format_debug(e)
            logging.error(e)


def file_priority_cmp(a, b):
    priority = {
        'ATM': 1,
        'MPAS_AM': 2,
        'MPAS_CICE': 3,
        'MPAS_RST': 4,
        'MPAS_O_IN': 5,
        'MPAS_CICE_IN': 6,
        'RPT': 7,
    }
    apriority = priority.get(a['type'])
    bpriority = priority.get(b['type'])
    if not apriority and not bpriority:
        return 1
    elif not apriority:
        apriority = 8
    elif not bpriority:
        bpriority = 8
    
    return apriority - bpriority


def raw_file_cmp(a, b):
    """
    Comparison function for incoming files

    Parameters
        a (file): the first operand
        b (file): the second operand

        the file consists of a filename, date, size and type
    """

    a = str(a['filename'].split('/')[-1])
    b = str(b['filename'].split('/')[-1])
    if not filter(str.isdigit, a) or not filter(str.isdigit, b):
        return a > b
    expression = '\d\d\d\d-\d\d.*'
    asearch = re.search(expression, a)
    if not asearch:
        return -1
    bsearch = re.search(expression, b)
    if not bsearch:
        return -1
    a_index = asearch.start()
    b_index = bsearch.start()
    a_walk_index = 4
    # while str(a[a_index + a_walk_index]).isdigit():
    #     a_walk_index += 1
    b_walk_index = 4
    # while str(b[b_index + b_walk_index]).isdigit():
    #     b_walk_index += 1
    a_year = int(a[a_index: a_index + a_walk_index])
    b_year = int(b[b_index: b_index + b_walk_index])
    if a_year > b_year:
        return 1
    elif a_year < b_year:
        return -1
    else:
        month_walk = 2
        # while a[a_index + a_walk_index + month_walk].isdigit():
        #     month_walk += 1
        a_month = int(a[a_index + a_walk_index + 1: a_index + a_walk_index + month_walk])
        b_month = int(b[b_index + b_walk_index + 1: b_index + b_walk_index + month_walk])
        if a_month > b_month:
            return 1
        elif a_month < b_month:
            return -1
        else:
            return 0

def raw_filename_cmp(a, b):
    """
    Comparison function for incoming files

    Parameters
        a (str): the first filename
        b (str): the second filename

    """

    a = a.split('/')[-1]
    b = b.split('/')[-1]
    expression = '\d\d\d\d-\d\d.*'
    asearch = re.search(expression, a)
    if not asearch:
        return -1
    bsearch = re.search(expression, b)
    if not bsearch:
        return -1
    a_index = asearch.start()
    b_index = bsearch.start()
    a_walk_index = 4
    # while str(a[a_index + a_walk_index]).isdigit():
    #     a_walk_index += 1
    b_walk_index = 4
    # while str(b[b_index + b_walk_index]).isdigit():
    #     b_walk_index += 1
    a_year = int(a[a_index: a_index + a_walk_index])
    b_year = int(b[b_index: b_index + b_walk_index])
    if a_year > b_year:
        return 1
    elif a_year < b_year:
        return -1
    else:
        month_walk = 2
        # while a[a_index + a_walk_index + month_walk].isdigit():
        #     month_walk += 1
        a_month = int(a[a_index + a_walk_index + 1: a_index + a_walk_index + month_walk])
        b_month = int(b[b_index + b_walk_index + 1: b_index + b_walk_index + month_walk])
        if a_month > b_month:
            return 1
        elif a_month < b_month:
            return -1
        else:
            return 0

def thread_sleep(seconds, event):
    """
    Allows a thread to sleep for one second at at time, and cancel when if the
    thread event is set
    """
    for i in range(seconds):
        if event and event.is_set():
            return 1
        sleep(1)
    return 0

def check_slurm_job_submission(expected_name):
    """
    Checks if a job with the expected_name is in the slurm queue
    """
    cmd = ['scontrol', 'show', 'job']
    job_id = 0
    found_job = False
    while True:
        while True:
            try:
                out = Popen(cmd, stdout=PIPE, stderr=PIPE).communicate()[0]
                break
            except:
                sleep(1)
        out = out.split('\n')
        if 'error' in out[0]:
            sleep(1)
            msg = 'Error checking job status for {0}'.format(expected_name)
            logging.warning(msg)
            continue
        for line in out:
            for word in line.split():
                if 'JobId' in word:
                    index = word.find('=') + 1
                    job_id = int(word[index:])
                    # continue
                if 'Name' in word:
                    index = word.find('=') + 1
                    if word[index:] == expected_name:
                        found_job = True

                if found_job and job_id != 0:
                    return found_job, job_id
        sleep(1)
    return found_job, job_id