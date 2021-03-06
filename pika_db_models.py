"""
SQLObject based database interface of models for pika calls/observation/etc.
    objects

#See sqlobject documentation for usage examples:
http://sqlobject.org/SQLObject.html

Tables:
    Observer
    Collection
    Observation
    Recording
    Calls

Each of the above tables is in a 1 to many relationship with the table below it
(e.g. an Observer may have many collections).  For more details about the objects
and their relationships see the docstrings for the corresponding models.
"""

from sqlobject import *
import sys
import os
import glob
import numpy as np

def init_db():
    #db_filename = os.path.abspath('pika.db')
    #if os.path.exists(db_filename):
        #os.unlink(db_filename)
    try:
        sqlhub.processConnection
    except AttributeError:
        connection_string = "sqlite:/D:/Workspace/pika/pika.db"
        connection = connectionForURI(connection_string)
        sqlhub.processConnection = connection

def init_observers():
    Observer(name="Jonathan Goff", institution="Pika Watch")
    Observer(name="Shankar Shivappa", institution="Pika Watch")

def init_tables(sure=False, really_sure=False):
    """NOTE: this should only work if the tables don't already exist.
    If you want to reset the database you could delete the database manually
    then run this function to initialize the tables.
    """
    if sure and really_sure:
        Observer.createTable(True)
        Collection.createTable(True)
        Observation.createTable(True)
        Recording.createTable(True)
        Call.createTable(True)
    
class Observer(SQLObject):
    name = StringCol()
    institution = StringCol(default=None)
    collections = MultipleJoin('Collection')

class Collection(SQLObject):
    """Collections may include recordings from multiple sublocations
    (each sublocation counting as a different observation) within the
    same general area and on the same trip.  They should be made by
    a single observer so if multiple people were recording at the same
    set of locations on a trip they should each have their own collection
    record for their recordings on that trip.

    example: Bob and Jane go on a trip to unicorn falls and observe pika
    at several talus slopes along the trail.  There should be two collection
    records - one for Bob and one for Jane.  All of the recordings Bob made
    on the trip should be within Bob's collection (similarly for Jane).
    Each sublocation for each of them should be its own observation record,
    see Observation class for details on what should be included there.
    """
    observer = ForeignKey("Observer")
    folder = StringCol()
    start_date = DateCol()
    end_date = DateCol(default=None)
    description = StringCol(default=None)
    notes = StringCol(default=None)
    processed = BoolCol(default=False)
    observations = MultipleJoin('Observation')

class Observation(SQLObject):
    """Observations should be from a single specific location with a
    single observer on a single trip, but may include multiple recordings.
    
    example: Bob makes several recordings at the third talus slope along the 
    trail to unicorn falls.  Each of these recordings can be considered part
    of the same observation.
    
    Bob continues on and also records at the fifth talus slope.  The recordings
    there should be considered a separate observation.
    """
    collection = ForeignKey("Collection")
    description = StringCol(default=None)
    latitude = FloatCol(default=None)
    longitude = FloatCol(default=None)
    datum = StringCol(default=None) #Should probably always be WGS84 or NAD83 (I believe are equivalent)
    count_estimate = IntCol(default=None)
    notes = StringCol(default=None)
    recordings = MultipleJoin('Recording')

class Recording(SQLObject):
    """Individual recordings.  There should be one record for every file collected.
    Every recording within a collection should be stored in the same folder.
    """
    
    observation = ForeignKey("Observation")
    filename = StringCol()
    start_time = DateTimeCol()
    duration = FloatCol()
    bitrate = FloatCol()
    device = StringCol(default=None)
    notes = StringCol(default=None)
    processed = BoolCol(default=False)
    calls = MultipleJoin("Call")
    
    def get_unverified_calls(self):
        return Call.select(AND(Call.q.verified==None,
                Call.q.recordingID == self.id))
    
    def output_folder(self):
        return os.path.dirname(self.filename) + "/recording{}/".format(self.id)
    
    def chunked_files(self):
        """
        Returns numpy array of offset_*.wav files corresponding to recording 
        (created from preprocessing the recording that occurs in the 
        pika.preprocess_collection method).
        The array is sorted in order of the offsets numerically rather than 
        lexicographically that way we get e.g. offset_37.0.wav before 
        offset_201.0.wav where as the order would be reversed in the 
        lexicographic sort.
        """
        wav_files = np.array(glob.glob(self.output_folder() + "offset_*.wav"))
        base_files = [os.path.basename(f) for f in wav_files]
        audio_offsets = np.array([float(f[7:f.find(".w")]) for f in base_files])
        wav_files = wav_files[audio_offsets.argsort()]
        return wav_files
        

class Call(SQLObject):
    """Identified pika calls.  One record for each pika call identified during processing."""
    recording = ForeignKey("Recording")
    verified = BoolCol(default=None)
    offset = FloatCol()
    duration = FloatCol()
    filename = StringCol()
